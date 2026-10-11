"""Import every module's models so Alembic and tests see the full metadata."""
from app.modules.audit import models as _audit  # noqa: F401
from app.modules.auth import models as _auth  # noqa: F401
from app.modules.users import models as _users  # noqa: F401
from app.modules.ledger import models as _ledger  # noqa: F401
from app.modules.wallet import models as _wallet  # noqa: F401
from app.modules.payments import models as _payments  # noqa: F401
from app.modules.providers import models as _providers  # noqa: F401
from app.modules.services import models as _services  # noqa: F401
from app.modules.transactions import models as _transactions  # noqa: F401
from app.modules.electricity import models as _electricity  # noqa: F401
from app.modules.education import models as _education  # noqa: F401

from app.modules.tv import models as _tv  # noqa: F401

from app.modules.notifications import models as _notifications  # noqa: F401

from app.modules.referrals import models as _referrals  # noqa: F401
from app.modules.promotions import models as _promotions  # noqa: F401

from app.modules.fraud import models as _fraud  # noqa: F401
from app.modules.reconciliation import models as _reconciliation  # noqa: F401
