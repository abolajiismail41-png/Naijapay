from celery import Celery

from app.core.config import get_settings

_s = get_settings()
celery_app = Celery("naijapay", broker=_s.redis_url, backend=None,
                    include=["app.workers.tasks_payments", "app.workers.tasks_transactions", "app.workers.tasks_notifications", "app.workers.tasks_risk"])
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_default_queue="default",
    timezone="UTC",
)


@celery_app.task(name="system.ping")
def ping() -> str:
    return "pong"

celery_app.conf.beat_schedule = {
    "payments-sweep": {"task": "payments.sweep", "schedule": 120.0},
    "transactions-sweep": {"task": "transactions.sweep", "schedule": 60.0},
    "provider-costs-sync": {"task": "providers.sync_costs", "schedule": 21600.0},
    "provider-float-check": {"task": "providers.check_float", "schedule": 300.0},
    "notifications-delivery": {"task": "notifications.deliver_due", "schedule": 15.0},
    "fraud-screening": {"task": "fraud.scan_recent", "schedule": 300.0},
    "daily-internal-reconciliation": {"task": "reconciliation.run_internal", "schedule": 86400.0},
}
