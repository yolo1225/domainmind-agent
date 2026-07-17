from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LearningResource, ReviewReport


EXPORT_ROOT = Path(__file__).resolve().parents[3] / "storage" / "exports"


def _safe_stem(value: str) -> str:
    return "".join(char for char in value if char.isalnum() or char in {"-", "_"})[:80]


def _export_content(resource: LearningResource, audience: str) -> str:
    if resource.resource_type != "graded_quiz" or audience == "teacher":
        return resource.content_md
    hidden_prefixes = ("参考答案：", "答案：", "解析：")
    return "\n".join(
        line for line in resource.content_md.splitlines()
        if not line.strip().startswith(hidden_prefixes)
    )


def _write_pdf(path: Path, resource: LearningResource, content: str) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from reportlab.lib.styles import ParagraphStyle

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    style = ParagraphStyle(
        "ChineseBody", fontName="STSong-Light", fontSize=10, leading=16
    )
    title_style = ParagraphStyle(
        "ChineseTitle", parent=style, fontSize=18, leading=24, spaceAfter=12
    )
    story = [Paragraph(resource.title, title_style)]
    for block in content.split("\n\n"):
        text = block.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        story.extend([Paragraph(text.replace("\n", "<br/>"), style), Spacer(1, 8)])
    SimpleDocTemplate(str(path), pagesize=A4, title=resource.title).build(story)


def export_resource(
    db: Session,
    resource: LearningResource,
    export_format: str,
    audience: str = "learner",
) -> dict:
    export_format = export_format.lower()
    if export_format not in {"markdown", "pdf"}:
        raise ValueError("export_format must be markdown or pdf")
    if audience not in {"learner", "teacher"}:
        raise ValueError("audience must be learner or teacher")
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    suffix = ".md" if export_format == "markdown" else ".pdf"
    export_id = f"exp_{uuid4().hex}"
    path = EXPORT_ROOT / f"{_safe_stem(resource.public_id)}_{export_id}{suffix}"
    content = _export_content(resource, audience)
    if export_format == "markdown":
        path.write_text(
            f"# {resource.title}\n\n{content}\n\n"
            f"---\n资源版本：{resource.version}\n审核状态：{resource.review_status}\n",
            encoding="utf-8",
        )
    else:
        _write_pdf(path, resource, content)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    report = db.scalar(
        select(ReviewReport)
        .where(ReviewReport.resource_id == resource.id)
        .order_by(ReviewReport.id.desc())
    )
    return {
        "export_id": export_id,
        "resource_id": resource.public_id,
        "resource_version": resource.version,
        "format": export_format,
        "audience": audience,
        "file_name": path.name,
        "file_hash": f"sha256:{digest}",
        "review_report_id": str(report.id) if report else None,
        "review_status": resource.review_status,
        "download_url": f"/api/v1/resources/exports/{path.name}",
    }


def resolve_export_path(file_name: str) -> Path:
    candidate = (EXPORT_ROOT / Path(file_name).name).resolve()
    if candidate.parent != EXPORT_ROOT.resolve() or not candidate.is_file():
        raise FileNotFoundError(file_name)
    return candidate
