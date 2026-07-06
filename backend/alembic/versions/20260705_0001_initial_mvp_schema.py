"""initial MVP schema

Revision ID: 20260705_0001
Revises:
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260705_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "demo_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_demo_users_public_id", "demo_users", ["public_id"])
    op.create_index("ix_demo_users_role", "demo_users", ["role"])

    op.create_table(
        "domains",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain_code"),
    )
    op.create_index("ix_domains_domain_code", "domains", ["domain_code"])

    op.create_table(
        "evaluation_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("profile_type", sa.String(length=64), nullable=False),
        sa.Column("expected_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_evaluation_cases_public_id", "evaluation_cases", ["public_id"])

    op.create_table(
        "knowledge_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("source_title", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("license_note", sa.String(length=255), nullable=False),
        sa.Column("needs_reembedding", sa.Boolean(), nullable=False),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_knowledge_items_domain_code", "knowledge_items", ["domain_code"])
    op.create_index("ix_knowledge_items_name", "knowledge_items", ["name"])
    op.create_index("ix_knowledge_items_public_id", "knowledge_items", ["public_id"])

    op.create_table(
        "learners",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("background", sa.String(length=255), nullable=False),
        sa.Column("target_domain", sa.String(length=64), nullable=False),
        sa.Column("experience_years", sa.Integer(), nullable=False),
        sa.Column("learning_style", sa.String(length=32), nullable=False),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_learners_public_id", "learners", ["public_id"])

    op.create_table(
        "knowledge_relations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_item_id", sa.Integer(), nullable=False),
        sa.Column("target_item_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["source_item_id"], ["knowledge_items.id"]),
        sa.ForeignKeyConstraint(["target_item_id"], ["knowledge_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "diagnostic_questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("knowledge_item_id", sa.Integer(), nullable=False),
        sa.Column("question_type", sa.String(length=32), nullable=False),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("answer_key_json", sa.JSON(), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["knowledge_item_id"], ["knowledge_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_diagnostic_questions_public_id", "diagnostic_questions", ["public_id"])

    op.create_table(
        "learner_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("ability_profile_json", sa.JSON(), nullable=False),
        sa.Column("weak_knowledge_json", sa.JSON(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_learner_profiles_public_id", "learner_profiles", ["public_id"])

    op.create_table(
        "answer_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_item_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("answer_summary_json", sa.JSON(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["knowledge_item_id"], ["knowledge_items.id"]),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["question_id"], ["diagnostic_questions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "generation_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resource_types_json", sa.JSON(), nullable=False),
        sa.Column("revision_count", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["learner_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_generation_tasks_public_id", "generation_tasks", ["public_id"])

    op.create_table(
        "learning_paths",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("path_json", sa.JSON(), nullable=False),
        sa.Column("needs_refresh", sa.Boolean(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["learner_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_learning_paths_public_id", "learning_paths", ["public_id"])

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("sender", sa.String(length=64), nullable=False),
        sa.Column("receiver", sa.String(length=64), nullable=False),
        sa.Column("message_type", sa.String(length=32), nullable=False),
        sa.Column("payload_summary_json", sa.JSON(), nullable=False),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_messages_session_id", "agent_messages", ["session_id"])
    op.create_index("ix_agent_messages_task_id", "agent_messages", ["task_id"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generation_task_id", sa.Integer(), nullable=True),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_summary_json", sa.JSON(), nullable=False),
        sa.Column("output_summary_json", sa.JSON(), nullable=False),
        sa.Column("llm_calls", sa.Integer(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["generation_task_id"], ["generation_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_agent_name", "agent_runs", ["agent_name"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])

    op.create_table(
        "learning_resources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("generation_task_id", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("learner_profile_type", sa.String(length=64), nullable=False),
        sa.Column("sources_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["generation_task_id"], ["generation_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_learning_resources_public_id", "learning_resources", ["public_id"])

    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("feedback_type", sa.String(length=32), nullable=False),
        sa.Column("feedback_summary_json", sa.JSON(), nullable=False),
        sa.Column("triggered_action", sa.String(length=64), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["learning_resources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "review_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("primary_review_json", sa.JSON(), nullable=False),
        sa.Column("secondary_review_json", sa.JSON(), nullable=False),
        sa.Column("arbitration_json", sa.JSON(), nullable=False),
        sa.Column("manual_review_required", sa.Boolean(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["resource_id"], ["learning_resources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("review_reports")
    op.drop_table("feedback")
    op.drop_index("ix_learning_resources_public_id", table_name="learning_resources")
    op.drop_table("learning_resources")
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent_name", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_agent_messages_task_id", table_name="agent_messages")
    op.drop_index("ix_agent_messages_session_id", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index("ix_learning_paths_public_id", table_name="learning_paths")
    op.drop_table("learning_paths")
    op.drop_index("ix_generation_tasks_public_id", table_name="generation_tasks")
    op.drop_table("generation_tasks")
    op.drop_table("answer_records")
    op.drop_index("ix_learner_profiles_public_id", table_name="learner_profiles")
    op.drop_table("learner_profiles")
    op.drop_index("ix_diagnostic_questions_public_id", table_name="diagnostic_questions")
    op.drop_table("diagnostic_questions")
    op.drop_table("knowledge_relations")
    op.drop_index("ix_learners_public_id", table_name="learners")
    op.drop_table("learners")
    op.drop_index("ix_knowledge_items_public_id", table_name="knowledge_items")
    op.drop_index("ix_knowledge_items_name", table_name="knowledge_items")
    op.drop_index("ix_knowledge_items_domain_code", table_name="knowledge_items")
    op.drop_table("knowledge_items")
    op.drop_index("ix_evaluation_cases_public_id", table_name="evaluation_cases")
    op.drop_table("evaluation_cases")
    op.drop_index("ix_domains_domain_code", table_name="domains")
    op.drop_table("domains")
    op.drop_index("ix_demo_users_role", table_name="demo_users")
    op.drop_index("ix_demo_users_public_id", table_name="demo_users")
    op.drop_table("demo_users")
