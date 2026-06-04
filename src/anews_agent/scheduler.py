from __future__ import annotations

from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler


def create_push_scheduler(
    push_job: Callable[[], None],
    *,
    interval_hours: int = 2,
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        push_job,
        "interval",
        hours=interval_hours,
        id="anews-push",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return scheduler
