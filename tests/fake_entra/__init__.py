"""A fake Microsoft Entra ID for the integration tests. Test tooling only."""

from .server import FakeEntra  # noqa: F401
from .state import HOME_TENANT, OTHER_TENANT, TENANTS  # noqa: F401
