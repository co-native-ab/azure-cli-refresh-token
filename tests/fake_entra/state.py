"""State of the fake identity provider: tenants, one user, one service principal, and failure modes.

Tests change this object directly while the server runs. Test tooling only.
"""

import threading
import time
from collections import namedtuple

HOME_TENANT = '11111111-1111-4111-8111-111111111111'
OTHER_TENANT = '22222222-2222-4222-8222-222222222222'

Tenant = namedtuple('Tenant', ['id', 'subscription_id', 'subscription_name'])
IssuedToken = namedtuple('IssuedToken', ['grant', 'tenant', 'scope', 'kind', 'text'])
TokenRequest = namedtuple('TokenRequest', ['grant_type', 'tenant', 'scope', 'claims'])

TENANTS = {
    HOME_TENANT: Tenant(HOME_TENANT, '33333333-3333-4333-8333-333333333333', 'Home subscription'),
    OTHER_TENANT: Tenant(OTHER_TENANT, '44444444-4444-4444-8444-444444444444',
                         'Other subscription'),
}

MODES = ('normal', 'interaction_required', 'same_token', 'stale_token', 'opaque_token',
         'bad_secret', 'expired_secret')


class State:
    def __init__(self):
        self.lock = threading.RLock()
        self.username = 'user@example.test'
        self.user_oid = '55555555-5555-4555-8555-555555555555'
        self.groups = ['66666666-6666-4666-8666-666666666666']
        self.app_id = '77777777-7777-4777-8777-777777777777'
        self.app_secret = 'not-a-real-secret'
        self.app_oid = '88888888-8888-4888-8888-888888888888'
        self.mode = 'normal'
        # Shifts the issue and expiry time of tokens issued while it is set, so a test can cache a
        # token that looks older than the proof's allowance.
        self.clock_offset_seconds = 0
        self.issued = []
        self.requests = []
        self.refresh_tokens = set()
        self.device_codes = {}
        self.last_access_token = {}

    def now(self):
        return time.time() + self.clock_offset_seconds

    def record_issued(self, grant, tenant, scope, kind, text):
        with self.lock:
            self.issued.append(IssuedToken(grant, tenant, scope, kind, text))

    def record_request(self, grant_type, tenant, scope, claims):
        with self.lock:
            self.requests.append(TokenRequest(grant_type, tenant, scope, claims))

    def requests_for(self, grant_type=None, scope=None):
        with self.lock:
            return [request for request in self.requests
                    if (grant_type is None or request.grant_type == grant_type)
                    and (scope is None or request.scope == scope)]

    def issued_tokens(self, kind=None):
        with self.lock:
            return [token for token in self.issued if kind is None or token.kind == kind]

    def all_issued_texts(self):
        """Every token text issued so far; used by leak checks and never printed."""
        with self.lock:
            return [token.text for token in self.issued]
