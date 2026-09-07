"""Fill a newly downloaded question-bank template from reviewed source rows.

The template owns all slot and fingerprint columns.  This tool only copies the
editable question fields after matching a row by knowledge name, purpose and
quiz level, so a workbook remains valid for the database state that generated
the template.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from openpyxl import load_workbook


SHEET_NAME = "题目"
KEY_HEADERS = ("知识点名称", "purpose", "quiz_level")
EDITABLE_HEADERS = (
    "题目类型",
    "难度",
    "题干",
    "选项A",
    "选项B",
    "选项C",
    "选项D",
    "正确答案",
    "解析",
    "评分点",
)


def _header_columns(sheet) -> dict[str, int]:
    return {
        str(cell.value or "").strip(): cell.column
        for cell in sheet[1]
        if str(cell.value or "").strip()
    }


def _key(sheet, row: int, columns: dict[str, int]) -> tuple[str, str, str]:
    return tuple(
        str(sheet.cell(row, columns[header]).value or "").strip()
        for header in KEY_HEADERS
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("template", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    template_book = load_workbook(args.template)
    # The source has only a few hundred rows. Normal mode keeps row lookups
    # constant-time while copying the editable cells below.
    source_book = load_workbook(args.source, data_only=True)
    try:
        template = template_book[SHEET_NAME]
        source = source_book[SHEET_NAME]
        template_columns = _header_columns(template)
        source_columns = _header_columns(source)
        required = {*KEY_HEADERS, *EDITABLE_HEADERS}
        for label, columns in (("template", template_columns), ("source", source_columns)):
            missing = required - set(columns)
            if missing:
                raise ValueError(f"{label}_headers_missing:{sorted(missing)}")

        source_rows: dict[tuple[str, str, str], int] = {}
        # The reviewed source has the same fixed slot count as the generated
        # template.  Bound the scan to that count because some spreadsheet
        # editors retain formatting across empty trailing rows.
        for row in range(2, template.max_row + 1):
            key = _key(source, row, source_columns)
            if not all(key):
                continue
            if key in source_rows:
                raise ValueError(f"source_duplicate_key:{key}")
            source_rows[key] = row

        template_keys: set[tuple[str, str, str]] = set()
        for row in range(2, template.max_row + 1):
            key = _key(template, row, template_columns)
            if not all(key):
                raise ValueError(f"template_key_missing:row_{row}")
            if key in template_keys:
                raise ValueError(f"template_duplicate_key:{key}")
            template_keys.add(key)
            source_row = source_rows.get(key)
            if source_row is None:
                raise ValueError(f"source_question_missing:{key}")
            for header in EDITABLE_HEADERS:
                template.cell(row, template_columns[header]).value = source.cell(
                    source_row, source_columns[header]
                ).value

        unused = set(source_rows) - template_keys
        if unused:
            raise ValueError(f"source_question_not_in_template:{sorted(unused)[:3]}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        template_book.save(args.output)
        print(f"filled_rows={len(template_keys)} output={args.output}")
    finally:
        source_book.close()
        template_book.close()


if __name__ == "__main__":
    main()
