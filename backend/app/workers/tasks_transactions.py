import logging
import uuid

from app.modules.providers import prices
from app.modules.transactions.execution import TransactionService
from app.workers.celery_app import celery_app
from app.workers.runtime import Runtime, run_job

log = logging.getLogger(__name__)


@celery_app.task(name="transactions.execute")
def execute(txn_id: str) -> None:
    run_job(lambda rt: TransactionService(rt.db, rt.redis, rt.settings, rt.providers).execute(uuid.UUID(txn_id)))


@celery_app.task(name="transactions.process_provider_webhook")
def process_provider_webhook(event_id: str) -> None:
    run_job(lambda rt: TransactionService(rt.db, rt.redis, rt.settings, rt.providers)
            .process_provider_webhook(uuid.UUID(event_id)))


@celery_app.task(name="transactions.sweep")
def sweep() -> int:
    return run_job(lambda rt: TransactionService(rt.db, rt.redis, rt.settings, rt.providers).sweep())


@celery_app.task(name="providers.sync_costs")
def sync_costs() -> None:
    async def job(rt: Runtime) -> None:
        r = await prices.sync_costs(rt.db, rt.providers["inlomax"], "inlomax")
        log.info("provider_costs_synced", extra={"updated": r.updated, "rejected": r.rejected})
    run_job(job)


@celery_app.task(name="providers.check_float")
def check_float() -> None:
    async def job(rt: Runtime) -> None:
        bal = await rt.providers["inlomax"].balance()
        await rt.redis.set("provider:float:inlomax", bal.kobo, ex=900)
        if bal.kobo < rt.settings.inlomax_float_alert_kobo:
            log.error("provider_float_low", extra={"balance_kobo": bal.kobo})
    run_job(job)
