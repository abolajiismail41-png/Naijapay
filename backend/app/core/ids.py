import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_seq = 0


def uuid7() -> uuid.UUID:
    """Time-ordered UUIDv7 (RFC 9562, method 1): a counter keeps ids strictly increasing within a process,
    so keyset pagination and event ordering are stable even for rows created in the same millisecond."""
    global _last_ms, _seq
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms > _last_ms:
            _last_ms, _seq = ms, int.from_bytes(os.urandom(2), "big") & 0x1FF
        else:
            _seq += 1
            if _seq > 0xFFF:
                _last_ms, _seq = _last_ms + 1, 0
        ms, seq = _last_ms, _seq
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | (seq & 0xFFF) << 64 | 0b10 << 62 | rand_b
    return uuid.UUID(int=value)
