from app.core.errors import AppError

# Best-effort number-prefix table. Numbers can be ported between networks, so a mismatch is only a
# warning the customer can confirm, never a hard block. Update as NCC allocations change.
_PREFIXES = {
    "MTN": ("0703", "0704", "0706", "0803", "0806", "0810", "0813", "0814", "0816", "0903", "0906", "0913", "0916"),
    "AIRTEL": ("0701", "0708", "0802", "0808", "0812", "0901", "0902", "0904", "0907", "0912"),
    "GLO": ("0705", "0805", "0807", "0811", "0815", "0905", "0915"),
    "9MOBILE": ("0809", "0817", "0818", "0908", "0909"),
}


class NetworkMismatchError(AppError):
    status_code, code = 409, "network_mismatch"
    user_message = "This number may not be on the selected network."


def guess_network(phone_e164: str) -> str | None:
    local = "0" + phone_e164[4:]
    return next((n for n, prefixes in _PREFIXES.items() if local.startswith(prefixes)), None)


def check_network(phone_e164: str, chosen: str, confirmed: bool) -> None:
    guess = guess_network(phone_e164)
    if guess and guess != chosen and not confirmed:
        raise NetworkMismatchError(
            f"This number looks like a {guess} number, but you selected {chosen}. Ported numbers are common: "
            "if you are sure the number is on the selected network, confirm and continue.")
