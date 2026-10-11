import re
from typing import Annotated, Any

from pydantic import BeforeValidator

_NATIONAL = re.compile(r"^[789][01]\d{8}$")


def normalize_phone(raw: Any) -> str:
    """Normalise Nigerian mobile numbers to +234XXXXXXXXXX."""
    if not isinstance(raw, str):
        raise ValueError("phone must be a string")
    digits = re.sub(r"[\s\-()]", "", raw)
    if digits.startswith("+234"):
        national = digits[4:]
    elif digits.startswith("234"):
        national = digits[3:]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        raise ValueError("enter a valid Nigerian phone number")
    if not _NATIONAL.match(national):
        raise ValueError("enter a valid Nigerian phone number")
    return f"+234{national}"


Phone = Annotated[str, BeforeValidator(normalize_phone)]
