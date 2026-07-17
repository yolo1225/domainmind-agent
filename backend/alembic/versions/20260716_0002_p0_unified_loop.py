"""P0 unified learning loop and review arbitration

Revision ID: 20260716_0002
Revises: 20260705_0001
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260716_0002"
down_revision: str | None = "20260705_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in _inspector().get_columns(table_name)}


def _add_missing_columns(table_name: str, columns: list[sa.Column]) -> None:
    existing = _column_names(table_name)
    missing = [column for column in columns if column.name not in existing]
    if not missing:
        return
    with op.batch_alter_table(table_name) as batch:
        for column in missing:
            batch.add_column(column)


def _ensure_non_null_text_column(table_name: str, column_name: str, fill_value: str) -> None:
    if column_name not in _column_names(table_name):
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(sa.Column(column_name, sa.Text(), nullable=True))
    table = sa.table(table_name, sa.column(column_name, sa.Text()))
    op.execute(table.update().where(table.c[column_name].is_(None)).values({column_name: fill_value}))
    with op.batch_alter_table(table_name) as batch:
        batch.alter_column(column_name, existing_type=sa.Text(), nullable=False, server_default=None)


def _ensure_foreign_key(
    table_name: str,
    constraint_name: str,
    referred_table: str,
    local_columns: list[str],
    remote_columns: list[str],
) -> None:
    existing = _inspector().get_foreign_keys(table_name)
    if any(
        foreign_key.get("name") == constraint_name
        or (
            foreign_key.get("referred_table") == referred_table
            and foreign_key.get("constrained_columns") == local_columns
        )
        for foreign_key in existing
    ):
        return
    with op.batch_alter_table(table_name) as batch:
        batch.create_foreign_key(
            constraint_name,
            referred_table,
            local_columns,
            remote_columns,
        )


def _ensure_index(table_name: str, index_name: str, columns: list[str], *, unique: bool = False) -> None:
    if any(index.get("name") == index_name for index in _inspector().get_indexes(table_name)):
        return
    op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    if _table_exists("feedback") and not _table_exists("resource_feedback"):
        op.rename_table("feedback", "resource_feedback")
    if not _table_exists("resource_feedback"):
        raise RuntimeError("Expected feedback or resource_feedback table before P0 migration")

    _add_missing_columns(
        "generation_tasks",
        [
            sa.Column("trigger_type", sa.String(32), nullable=False, server_default="initial_generation"),
            sa.Column("execution_mode", sa.String(16), nullable=False, server_default="auto"),
            sa.Column("learning_goal", sa.String(512), nullable=False, server_default=""),
            sa.Column("source_resource_id", sa.Integer(), nullable=True),
            sa.Column("source_feedback_id", sa.Integer(), nullable=True),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        ],
    )

    _add_missing_columns(
        "learner_profiles",
        [
            sa.Column("profile_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("previous_profile_id", sa.Integer(), nullable=True),
            sa.Column("changed_dimensions_json", sa.JSON(), nullable=False, server_default=sa.text("('[]')")),
            sa.Column("evidence_refs_json", sa.JSON(), nullable=False, server_default=sa.text("('[]')")),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("trigger_feedback_id", sa.Integer(), nullable=True),
            sa.Column("profile_changed_at", sa.DateTime(timezone=True), nullable=True),
        ],
    )
    _ensure_non_null_text_column("learner_profiles", "decision_reason", "initial profile")
    _ensure_foreign_key(
        "learner_profiles", "fk_profile_previous", "learner_profiles", ["previous_profile_id"], ["id"]
    )
    _ensure_foreign_key(
        "learner_profiles",
        "fk_profile_trigger_feedback",
        "resource_feedback",
        ["trigger_feedback_id"],
        ["id"],
    )

    _add_missing_columns(
        "learning_resources",
        [
            sa.Column("series_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("previous_resource_id", sa.Integer(), nullable=True),
            sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        ],
    )
    _ensure_non_null_text_column("learning_resources", "adaptation_reason", "")
    _ensure_foreign_key(
        "learning_resources",
        "fk_resource_previous",
        "learning_resources",
        ["previous_resource_id"],
        ["id"],
    )
    _ensure_index("learning_resources", "ix_learning_resources_series_id", ["series_id"])
    _ensure_index("learning_resources", "ix_learning_resources_is_current", ["is_current"])

    op.execute("UPDATE learning_resources SET series_id = public_id WHERE series_id = ''")

    _add_missing_columns(
        "agent_runs",
        [
            sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("model_name", sa.String(128), nullable=True),
            sa.Column("prompt_version", sa.String(32), nullable=False, server_default="v1"),
        ],
    )

    _add_missing_columns(
        "review_reports",
        [
            sa.Column("task_id", sa.Integer(), nullable=True),
            sa.Column("factual_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("source_trace_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("difficulty_match_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("coverage_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("decision", sa.String(32), nullable=False, server_default="revision_required"),
            sa.Column("evidence_refs_json", sa.JSON(), nullable=False, server_default=sa.text("('[]')")),
            sa.Column("disagreement_summary_json", sa.JSON(), nullable=False, server_default=sa.text("('{}')")),
            sa.Column("review_rule_version", sa.String(32), nullable=False, server_default="review-v1"),
            sa.Column("issues_json", sa.JSON(), nullable=False, server_default=sa.text("('[]')")),
            sa.Column("suggestions_json", sa.JSON(), nullable=False, server_default=sa.text("('[]')")),
        ],
    )
    _ensure_foreign_key("review_reports", "fk_review_task", "generation_tasks", ["task_id"], ["id"])

    rating_column = next(
        column for column in _inspector().get_columns("resource_feedback") if column["name"] == "rating"
    )
    if not rating_column["nullable"]:
        with op.batch_alter_table("resource_feedback") as batch:
            batch.alter_column("rating", existing_type=sa.Integer(), nullable=True)
    _add_missing_columns(
        "resource_feedback",
        [
            sa.Column("tutoring_session_id", sa.Integer(), nullable=True),
            sa.Column("tutoring_message_id", sa.Integer(), nullable=True),
            sa.Column("feedback_intent", sa.String(32), nullable=True),
            sa.Column("recommended_action", sa.String(32), nullable=True),
            sa.Column("profile_update_required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("profile_change_evidence_json", sa.JSON(), nullable=False, server_default=sa.text("('[]')")),
            sa.Column("decision_confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("affected_knowledge_ids_json", sa.JSON(), nullable=False, server_default=sa.text("('[]')")),
            sa.Column("affected_path_node_ids_json", sa.JSON(), nullable=False, server_default=sa.text("('[]')")),
            sa.Column("affected_resource_ids_json", sa.JSON(), nullable=False, server_default=sa.text("('[]')")),
        ],
    )
    _ensure_non_null_text_column("resource_feedback", "comment", "")
    _ensure_non_null_text_column("resource_feedback", "decision_reason", "")

    if not _table_exists("tutoring_sessions"):
        op.create_table(
            "tutoring_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("public_id", sa.String(64), nullable=False, unique=True),
            sa.Column("learner_id", sa.Integer(), sa.ForeignKey("learners.id"), nullable=False),
            sa.Column("resource_id", sa.Integer(), sa.ForeignKey("learning_resources.id"), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    _ensure_index("tutoring_sessions", "ix_tutoring_sessions_public_id", ["public_id"], unique=True)

    if not _table_exists("tutoring_messages"):
        op.create_table(
            "tutoring_messages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("public_id", sa.String(64), nullable=False, unique=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("tutoring_sessions.id"), nullable=False),
            sa.Column("sender", sa.String(32), nullable=False),
            sa.Column("message_type", sa.String(32), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("feedback_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    _ensure_index("tutoring_messages", "ix_tutoring_messages_public_id", ["public_id"], unique=True)

    if not _table_exists("manual_review_tasks"):
        op.create_table(
            "manual_review_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("public_id", sa.String(64), nullable=False, unique=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("generation_tasks.id"), nullable=False),
            sa.Column("resource_id", sa.Integer(), sa.ForeignKey("learning_resources.id"), nullable=True),
            sa.Column("review_report_id", sa.Integer(), sa.ForeignKey("review_reports.id"), nullable=True),
            sa.Column("trigger_reason", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("decision", sa.String(32), nullable=True),
            sa.Column("review_comment", sa.Text(), nullable=True),
            sa.Column("reviewed_by", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    _ensure_index("manual_review_tasks", "ix_manual_review_tasks_public_id", ["public_id"], unique=True)

    if not _table_exists("graph_checkpoints"):
        op.create_table(
            "graph_checkpoints",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.String(64), nullable=False, unique=True),
            sa.Column("checkpoint_id", sa.String(64), nullable=False),
            sa.Column("state_json", sa.JSON(), nullable=False),
            sa.Column("next_node", sa.String(64), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="saved"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    _ensure_index("graph_checkpoints", "ix_graph_checkpoints_task_id", ["task_id"], unique=True)
    _ensure_index("graph_checkpoints", "ix_graph_checkpoints_checkpoint_id", ["checkpoint_id"])

    _ensure_foreign_key(
        "generation_tasks",
        "fk_generation_source_resource",
        "learning_resources",
        ["source_resource_id"],
        ["id"],
    )
    _ensure_foreign_key(
        "generation_tasks",
        "fk_generation_source_feedback",
        "resource_feedback",
        ["source_feedback_id"],
        ["id"],
    )
    _ensure_foreign_key(
        "resource_feedback",
        "fk_feedback_tutoring_session",
        "tutoring_sessions",
        ["tutoring_session_id"],
        ["id"],
    )
    _ensure_foreign_key(
        "resource_feedback",
        "fk_feedback_tutoring_message",
        "tutoring_messages",
        ["tutoring_message_id"],
        ["id"],
    )
    _ensure_foreign_key(
        "tutoring_messages",
        "fk_tutoring_message_feedback",
        "resource_feedback",
        ["feedback_id"],
        ["id"],
    )


def downgrade() -> None:
    with op.batch_alter_table("tutoring_messages") as batch:
        batch.drop_constraint("fk_tutoring_message_feedback", type_="foreignkey")
    with op.batch_alter_table("resource_feedback") as batch:
        batch.drop_constraint("fk_feedback_tutoring_message", type_="foreignkey")
        batch.drop_constraint("fk_feedback_tutoring_session", type_="foreignkey")
    with op.batch_alter_table("generation_tasks") as batch:
        batch.drop_constraint("fk_generation_source_feedback", type_="foreignkey")
        batch.drop_constraint("fk_generation_source_resource", type_="foreignkey")
    with op.batch_alter_table("learner_profiles") as batch:
        batch.drop_constraint("fk_profile_trigger_feedback", type_="foreignkey")
    op.drop_table("graph_checkpoints")
    op.drop_table("manual_review_tasks")
    op.drop_table("tutoring_messages")
    op.drop_table("tutoring_sessions")

    with op.batch_alter_table("resource_feedback") as batch:
        for column in (
            "decision_reason",
            "affected_resource_ids_json",
            "affected_path_node_ids_json",
            "affected_knowledge_ids_json",
            "decision_confidence",
            "profile_change_evidence_json",
            "profile_update_required",
            "recommended_action",
            "feedback_intent",
            "tutoring_message_id",
            "tutoring_session_id",
            "comment",
        ):
            batch.drop_column(column)
        batch.alter_column("rating", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("review_reports") as batch:
        batch.drop_constraint("fk_review_task", type_="foreignkey")
        for column in (
            "suggestions_json",
            "issues_json",
            "review_rule_version",
            "disagreement_summary_json",
            "evidence_refs_json",
            "decision",
            "coverage_score",
            "difficulty_match_score",
            "source_trace_score",
            "factual_score",
            "task_id",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("agent_runs") as batch:
        for column in ("prompt_version", "model_name", "tokens_output", "tokens_input"):
            batch.drop_column(column)

    with op.batch_alter_table("learning_resources") as batch:
        batch.drop_index("ix_learning_resources_is_current")
        batch.drop_index("ix_learning_resources_series_id")
        batch.drop_constraint("fk_resource_previous", type_="foreignkey")
        for column in ("adaptation_reason", "is_current", "previous_resource_id", "series_id"):
            batch.drop_column(column)

    with op.batch_alter_table("learner_profiles") as batch:
        batch.drop_constraint("fk_profile_previous", type_="foreignkey")
        for column in (
            "profile_changed_at",
            "decision_reason",
            "trigger_feedback_id",
            "confidence",
            "evidence_refs_json",
            "changed_dimensions_json",
            "previous_profile_id",
            "profile_version",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("generation_tasks") as batch:
        for column in (
            "progress",
            "source_feedback_id",
            "source_resource_id",
            "learning_goal",
            "execution_mode",
            "trigger_type",
        ):
            batch.drop_column(column)

    op.rename_table("resource_feedback", "feedback")
