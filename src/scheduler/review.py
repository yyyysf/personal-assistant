"""周复盘生成：手动触发与定时任务共用。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.core.stats import weekly_review_payload
from src.llm.assistant import generate_weekly_review
from src.models import WeeklyReview

logger = get_logger(__name__)


def generate_and_store_review(db: Session) -> WeeklyReview:
    payload = weekly_review_payload(db)
    content, suggestions, source = generate_weekly_review(payload)
    week_start = payload["week_start"]

    review = db.scalar(select(WeeklyReview).where(WeeklyReview.week_start == week_start))
    if review is None:
        review = WeeklyReview(week_start=week_start)
        db.add(review)
    review.content = content
    review.suggestions = suggestions
    review.source = source
    db.commit()
    db.refresh(review)
    logger.info("周复盘已生成（%s）", source)
    return review
