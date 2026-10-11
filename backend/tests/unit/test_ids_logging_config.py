import json
import logging

import pytest

from app.core.config import Settings
from app.core.ids import uuid7
from app.core.logging import JsonFormatter


def test_uuid7_version_and_ordering() -> None:
    a, b = uuid7(), uuid7()
    assert a.version == 7 and b.version == 7
    assert a != b


def test_uuid7_is_strictly_increasing_within_a_process() -> None:
    ids = [uuid7() for _ in range(5000)]
    assert ids == sorted(ids) and len(set(ids)) == 5000


def test_log_redacts_sensitive_fields() -> None:
    rec = logging.LogRecord("t", logging.INFO, "", 0, "hi", (), None)
    rec.password = "hunter2"
    rec.amount = 5
    out = json.loads(JsonFormatter().format(rec))
    assert out["password"] == "[REDACTED]" and out["amount"] == 5


def _settings(**kw: object) -> Settings:
    base = dict(database_url="x", redis_url="y", jwt_secret="a", encryption_key="b", webhook_secret="c")
    return Settings(_env_file=None, **{**base, **kw})  # type: ignore[arg-type]


def test_production_rejects_weak_secrets() -> None:
    with pytest.raises(ValueError):
        _settings(environment="production")


def test_production_accepts_strong_secrets() -> None:
    strong = "x" * 40
    s = _settings(environment="production", jwt_secret=strong, encryption_key=strong[::-1] + "k",
                  webhook_secret=strong + "w", cors_origins=["https://app.example.com"])
    assert s.is_production


def test_production_rejects_wildcard_cors() -> None:
    strong = "x" * 40
    with pytest.raises(ValueError):
        _settings(environment="production", jwt_secret=strong, encryption_key=strong,
                  webhook_secret=strong, cors_origins=["*"])
