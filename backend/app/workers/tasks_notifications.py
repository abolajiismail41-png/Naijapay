from app.modules.notifications.delivery import deliver_due
from app.workers.celery_app import celery_app
from app.workers.runtime import run_job


@celery_app.task(name="notifications.deliver_due")
def deliver_notifications() -> int:
    return run_job(lambda rt: deliver_due(rt.db, rt.settings, rt.http))
