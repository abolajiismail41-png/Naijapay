"""Reference data shared by the migration and the test schema. Values are starting points an admin edits."""
from app.core.ids import uuid7

# Inlomax airtime serviceIDs and API discounts from https://inlomax.com/pricing (bps). Replaced by sync.
AIRTIME_COSTS = [("MTN", "1", 250), ("AIRTEL", "2", 200), ("GLO", "3", 400), ("9MOBILE", "4", 300)]
DEFAULT_AIRTIME_MARKUP_BPS = 200  # 2.00% placeholder: set your real markup in the admin pricing screen


def seed_statements() -> list[tuple[str, dict[str, object]]]:
    stmts: list[tuple[str, dict[str, object]]] = []
    for network, sid, bps in AIRTIME_COSTS:
        stmts.append((
            "INSERT INTO provider_prices (id, provider_code, category, scope_key, provider_service_id, kind, value, source) "
            "VALUES (:id, 'inlomax', 'AIRTIME', :n, :sid, 'DISCOUNT_BPS', :v, 'SEED') ON CONFLICT DO NOTHING",
            {"id": uuid7(), "n": network, "sid": sid, "v": bps}))
    stmts.append((
        "INSERT INTO pricing_rules (id, category, method, markup_bps, cap_at_face, note) "
        "VALUES (:id, 'AIRTIME', 'PERCENT_MARKUP', :bps, true, 'initial default') ON CONFLICT DO NOTHING",
        {"id": uuid7(), "bps": DEFAULT_AIRTIME_MARKUP_BPS}))
    return stmts


def seed_data_statements() -> list[tuple[str, dict[str, object]]]:
    """Data plans themselves are never seeded: they come from the provider sync and start unlisted."""
    return [("INSERT INTO pricing_rules (id, category, method, markup_bps, rounding_kobo, note) "
             "VALUES (:id, 'DATA', 'PERCENT_MARKUP', 300, 100, 'initial default') ON CONFLICT DO NOTHING",
             {"id": uuid7()})]


def seed_electricity_statements() -> list[tuple[str, dict[str, object]]]:
    """Placeholder: customers pay the token value plus a flat NGN 50 service fee. Edit in the admin pricing screen."""
    return [("INSERT INTO pricing_rules (id, category, method, fee_kobo, note) "
             "VALUES (:id, 'ELECTRICITY', 'FACE_VALUE', 5000, 'initial default') ON CONFLICT DO NOTHING",
             {"id": uuid7()})]


def seed_education_statements() -> list[tuple[str, dict[str, object]]]:
    """Placeholder: NGN 50 fixed markup PER PIN, whole-naira rounding. Edit in the admin pricing screen."""
    return [("INSERT INTO pricing_rules (id, category, method, markup_kobo, rounding_kobo, note) "
             "VALUES (:id, 'EDUCATION', 'FIXED_MARKUP', 5000, 100, 'initial default') ON CONFLICT DO NOTHING",
             {"id": uuid7()})]


def seed_tv_statements() -> list[tuple[str, dict[str, object]]]:
    """Conservative starting markup; operators must configure real provider costs and review prices."""
    return [
        ("INSERT INTO pricing_rules (id, category, method, markup_kobo, rounding_kobo, note) "
         "VALUES (:id, 'TV', 'FIXED_MARKUP', 5000, 100, 'initial default') ON CONFLICT DO NOTHING",
         {"id": uuid7()})
    ]
