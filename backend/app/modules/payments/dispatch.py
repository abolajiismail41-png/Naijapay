import logging
import uuid
from typing import Protocol

log = logging.getLogger(__name__)


class Dispatcher(Protocol):
    def enqueue_webhook(self, event_id: uuid.UUID) -> None: ...
    def enqueue_execute(self, txn_id: uuid.UUID) -> None: ...
    def enqueue_provider_webhook(self, event_id: uuid.UUID) -> None: ...


class CeleryDispatcher:
    """Sends tasks by name so request-path code never imports worker code."""

    @staticmethod
    def _send(name: str, arg: uuid.UUID) -> None:
        from app.workers.celery_app import celery_app
        celery_app.send_task(name, args=[str(arg)])

    def enqueue_webhook(self, event_id: uuid.UUID) -> None:
        self._send("payments.process_webhook_event", event_id)

    def enqueue_execute(self, txn_id: uuid.UUID) -> None:
        self._send("transactions.execute", txn_id)

    def enqueue_provider_webhook(self, event_id: uuid.UUID) -> None:
        self._send("transactions.process_provider_webhook", event_id)
