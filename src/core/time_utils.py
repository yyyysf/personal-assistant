"""本地时间工具：统一以服务器本地时间计算周与连续记录。"""

from datetime import date, datetime, time, timedelta


def now() -> datetime:
    return datetime.now()


def today() -> date:
    return now().date()


def week_start(day: date | None = None) -> date:
    target = day or today()
    return target - timedelta(days=target.weekday())


def week_end(day: date | None = None) -> date:
    return week_start(day) + timedelta(days=6)


def week_start_dt(day: date | None = None) -> datetime:
    return datetime.combine(week_start(day), time.min)


def week_end_dt(day: date | None = None) -> datetime:
    return datetime.combine(week_end(day) + timedelta(days=1), time.min)


def days_ago(days: int) -> date:
    return today() - timedelta(days=days)


def streak_days(active_days: set[date], anchor: date | None = None) -> int:
    """连续记录天数：今天有记录从今天算起，否则从昨天算起。"""
    current = anchor or today()
    if current not in active_days:
        current -= timedelta(days=1)
    streak = 0
    while current in active_days:
        streak += 1
        current -= timedelta(days=1)
    return streak
