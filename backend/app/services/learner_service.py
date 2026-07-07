from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Learner


def get_or_create_demo_learner(db: Session, learner_public_id: str = "learner_001") -> Learner:
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_public_id))
    if learner is not None:
        return learner
    learner = Learner(
        public_id=learner_public_id,
        background="MVP 演示学习者",
        target_domain="ai_app_dev",
        experience_years=0,
        learning_style="mixed",
    )
    db.add(learner)
    db.flush()
    return learner
