"""APScheduler 服务内定时任务：论文抓取、RSS 聚合、每周复盘。"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.config import settings
from src.core.db import SessionLocal
from src.core.logging import get_logger
from src.scheduler.fetchers import fetch_arxiv, fetch_rss
from src.scheduler.review import generate_and_store_review

logger = get_logger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_arxiv_job() -> None:
    with SessionLocal() as db:
        try:
            fetch_arxiv(db)
        except Exception as exc:
            logger.exception("arXiv 定时任务失败：%s", exc)


def _run_rss_job() -> None:
    with SessionLocal() as db:
        try:
            fetch_rss(db)
        except Exception as exc:
            logger.exception("RSS 定时任务失败：%s", exc)


def _run_review_job() -> None:
    with SessionLocal() as db:
        try:
            generate_and_store_review(db)
        except Exception as exc:
            logger.exception("周复盘定时任务失败：%s", exc)


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if not settings.enable_scheduler:
        logger.info("定时任务已关闭（ENABLE_SCHEDULER=false）")
        return None
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(
        _run_arxiv_job,
        CronTrigger(
            hour=settings.arxiv_fetch_hour,
            minute=settings.arxiv_fetch_minute,
            timezone=settings.timezone,
        ),
        id="arxiv_daily",
        name="arXiv cs.AI 每日论文抓取",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _run_rss_job,
        CronTrigger(
            hour=settings.rss_fetch_hour,
            minute=settings.rss_fetch_minute,
            timezone=settings.timezone,
        ),
        id="rss_daily",
        name="RSS 资讯每日聚合",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _run_review_job,
        CronTrigger(day_of_week="sun", hour=20, minute=10, timezone=settings.timezone),
        id="weekly_review",
        name="每周 AI 复盘",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "定时任务已启动：论文 %s:%02d，RSS %s:%02d，周日 20:10 复盘",
        settings.arxiv_fetch_hour,
        settings.arxiv_fetch_minute,
        settings.rss_fetch_hour,
        settings.rss_fetch_minute,
    )
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("定时任务已停止")


def scheduler_status() -> dict:
    if not settings.enable_scheduler:
        return {"enabled": False, "running": False, "jobs": []}
    if _scheduler is None:
        return {"enabled": True, "running": False, "jobs": []}
    jobs = []
    for job in _scheduler.get_jobs():
        next_run = job.next_run_time.isoformat() if job.next_run_time else None
        jobs.append({"id": job.id, "name": job.name, "next_run": next_run})
    return {"enabled": True, "running": _scheduler.running, "jobs": jobs}
