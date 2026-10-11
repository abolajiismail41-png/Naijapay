import uuid

import pytest

from app.core.money import Money
from app.modules.ledger.errors import UnbalancedJournalError
from app.modules.ledger.service import Direction, EntryLine, hash_request, validate_lines

A, B = uuid.uuid4(), uuid.uuid4()


def _lines(d: int, c: int) -> list[EntryLine]:
    return [EntryLine(A, Direction.DEBIT, Money(d)), EntryLine(B, Direction.CREDIT, Money(c))]


def test_balanced_ok() -> None:
    validate_lines(_lines(500, 500))


@pytest.mark.parametrize("d,c", [(500, 499), (0, 0), (-5, -5)])
def test_unbalanced_or_nonpositive_rejected(d: int, c: int) -> None:
    with pytest.raises(UnbalancedJournalError):
        validate_lines(_lines(d, c))


def test_single_line_rejected() -> None:
    with pytest.raises(UnbalancedJournalError):
        validate_lines([EntryLine(A, Direction.DEBIT, Money(5))])


def test_hash_is_order_independent_and_payload_sensitive() -> None:
    a = _lines(500, 500)
    assert hash_request("k", a) == hash_request("k", list(reversed(a)))
    assert hash_request("k", a) != hash_request("k", _lines(501, 501))
    assert hash_request("k", a) != hash_request("other", a)
