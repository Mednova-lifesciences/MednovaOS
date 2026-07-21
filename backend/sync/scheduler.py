from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .sync_engine import run_sync
from .utils import configure_logging, get_setting

logger = configure_logging()


class SyncScheduler:
    def __init__(self, app=None) -> None:
        self.scheduler = BackgroundScheduler()
        self.app = app
        self.enabled = get_setting("SYNC_SCHEDULER_ENABLED", "true").lower() == "true"
        self.cron = get_setting("SYNC_CRON", "0 2 * * *")

    def start(self) -> None:
        if not self.enabled or self.scheduler.running:
            return
        self.scheduler.add_job(run_sync, trigger=CronTrigger.from_crontab(self.cron), id="greenbook-sync", replace_existing=True)
        self.scheduler.start()
        logger.info("Scheduler started with cron expression: %s", self.cron)

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
