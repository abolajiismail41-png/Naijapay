from app.modules.fraud.service import scan_recent_transactions
from app.modules.reconciliation.service import run_internal_reconciliation
from app.workers.celery_app import celery_app
from app.workers.runtime import Runtime, run_job


@celery_app.task(name="fraud.scan_recent")
def scan_recent() -> int:
    return run_job(lambda rt: scan_recent_transactions(rt.db, rt.settings))


@celery_app.task(name="reconciliation.run_internal")
def reconcile_internal() -> dict:
    return run_job(lambda rt: run_internal_reconciliation(rt.db))
