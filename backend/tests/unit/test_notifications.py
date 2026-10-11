from datetime import UTC, datetime

from app.modules.notifications.service import delivery_retry_time


def test_delivery_retry_uses_bounded_exponential_backoff() -> None:
    now = datetime.now(UTC)
    first = delivery_retry_time(1)
    late = delivery_retry_time(100)
    assert 50 <= (first - now).total_seconds() <= 70
    assert 6 * 3600 - 5 <= (late - now).total_seconds() <= 6 * 3600 + 5
