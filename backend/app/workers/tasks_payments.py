import uuid

from app.modules.payments.errors import ProcessorUnavailableError
from app.modules.payments.service import FundingService
from app.workers.celery_app import celery_app
from app.workers.runtime import run_job


@celery_app.task(name="payments.process_webhook_event", bind=True,
                 autoretry_for=(ProcessorUnavailableError,), retry_backoff=True,
                 retry_backoff_max=600, retry_jitter=True, max_retries=8)
def process_webhook_event(self, event_id: str) -> None:  # type: ignore[no-untyped-def]
    run_job(lambda rt: FundingService(rt.db, rt.redis, rt.settings, rt.processor)
            .process_webhook_event(uuid.UUID(event_id)))


@celery_app.task(name="payments.sweep")
def sweep() -> int:
    return run_job(lambda rt: FundingService(rt.db, rt.redis, rt.settings, rt.processor).sweep())
