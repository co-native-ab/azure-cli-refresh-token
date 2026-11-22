"""A small local stand-in for Microsoft Entra ID, for tests only.

It serves only the part of the protocol that the Azure CLI and MSAL use: OpenID discovery, the
device-code endpoint, the token endpoint with the device-code, refresh-token and client-credentials
grants, the Azure Resource Manager cloud metadata, and the subscription list. Each behaviour copied
from the real service is a simplification, so a passing test shows agreement with this model, not
with the real service.

It is never part of the wheel and is not a tool for users.
"""

import base64
import json
import secrets
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import certs, state as state_module, tokens

RESERVED_SCOPES = ('openid', 'profile', 'offline_access')
RESOURCES = {
    'active_directory_resource_id': 'https://management.example.test/',
    'active_directory_graph_resource_id': 'https://aadgraph.example.test/',
    'microsoft_graph_resource_id': 'https://graph.example.test/',
    'batch_resource_id': 'https://batch.example.test/',
    'media_resource_id': 'https://media.example.test/',
    'ossrdbms_resource_id': 'https://ossrdbms.example.test/',
    'active_directory_data_lake_resource_id': 'https://datalake.example.test/',
}


def resource_of(scope):
    """The audience a scope asks for, as Microsoft Entra ID derives it."""
    if scope.endswith('/.default'):
        return scope[:-len('/.default')]
    return scope.rsplit('/', 1)[0]


def unverified_payload(token):
    """Decode the payload of a token this fake issued. Used to find the tenant of a bearer token."""
    segment = token.split('.')[1]
    return json.loads(base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4)))


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):  # noqa: A002 - signature fixed by the base class
        pass

    # ---- plumbing -------------------------------------------------------------------------

    @property
    def fake(self):
        return self.server.fake

    def send_json(self, status, body):
        data = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_form(self):
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length).decode('utf-8')
        return {key: values[0] for key, values in parse_qs(raw, keep_blank_values=True).items()}

    def path_parts(self):
        return [part for part in urlsplit(self.path).path.split('/') if part]

    # ---- routing --------------------------------------------------------------------------

    def do_GET(self):  # noqa: N802 - name fixed by the base class
        parts = self.path_parts()
        if parts == ['metadata', 'endpoints']:
            return self.send_json(200, self.fake.metadata())
        if parts == ['subscriptions']:
            return self.subscriptions()
        if len(parts) == 4 and parts[1:] == ['v2.0', '.well-known', 'openid-configuration']:
            return self.discovery(parts[0])
        return self.send_json(404, {'error': 'not_found', 'path': urlsplit(self.path).path})

    def do_POST(self):  # noqa: N802 - name fixed by the base class
        parts = self.path_parts()
        form = self.read_form()
        if len(parts) == 4 and parts[1:3] == ['oauth2', 'v2.0']:
            if parts[3] == 'devicecode':
                return self.device_code(parts[0], form)
            if parts[3] == 'token':
                return self.token(parts[0], form)
        return self.send_json(404, {'error': 'not_found', 'path': urlsplit(self.path).path})

    # ---- endpoints ------------------------------------------------------------------------

    def discovery(self, tenant):
        base = self.fake.base_url
        self.send_json(200, {
            'issuer': '{}/{}/v2.0'.format(base, tenant),
            'authorization_endpoint': '{}/{}/oauth2/v2.0/authorize'.format(base, tenant),
            'token_endpoint': '{}/{}/oauth2/v2.0/token'.format(base, tenant),
            'device_authorization_endpoint': '{}/{}/oauth2/v2.0/devicecode'.format(base, tenant),
        })

    def subscriptions(self):
        tenant_id = state_module.HOME_TENANT
        bearer = self.headers.get('Authorization', '')
        if bearer.startswith('Bearer '):
            try:
                tenant_id = unverified_payload(bearer[len('Bearer '):]).get('tid', tenant_id)
            except (ValueError, IndexError):
                pass
        tenant = state_module.TENANTS.get(tenant_id, state_module.TENANTS[state_module.HOME_TENANT])
        self.send_json(200, {'value': [{
            'id': '/subscriptions/' + tenant.subscription_id,
            'subscriptionId': tenant.subscription_id,
            'tenantId': tenant.id,
            'displayName': tenant.subscription_name,
            'state': 'Enabled',
            'subscriptionPolicies': {'locationPlacementId': 'Public_2014-09-01',
                                     'quotaId': 'Test_2014-09-01', 'spendingLimit': 'Off'},
            'authorizationSource': 'RoleBased',
        }]})

    def device_code(self, tenant, form):
        code = secrets.token_urlsafe(24)
        with self.fake.state.lock:
            self.fake.state.device_codes[code] = form.get('scope', '')
        self.send_json(200, {
            'device_code': code,
            'user_code': 'TESTCODE',
            'verification_uri': self.fake.base_url + '/devicelogin',
            'expires_in': 900,
            'interval': 1,
            'message': 'Test device code; the fake approves it at the first poll.',
        })

    def token(self, tenant, form):
        grant = form.get('grant_type', '')
        state = self.fake.state
        scope = ' '.join(s for s in form.get('scope', '').split() if s not in RESERVED_SCOPES)
        if grant.endswith('device_code'):
            scope = ' '.join(s for s in state.device_codes.get(form.get('device_code'), '').split()
                             if s not in RESERVED_SCOPES)
        state.record_request(grant, tenant, scope, form.get('claims'))

        if grant.endswith('device_code'):
            if form.get('device_code') not in state.device_codes:
                return self.error(400, 'invalid_grant', 'AADSTS70000: Unknown device code.', [70000])
            return self.user_tokens(grant, tenant, scope, mode='normal')

        if grant == 'refresh_token':
            if form.get('refresh_token') not in state.refresh_tokens:
                return self.error(400, 'invalid_grant', 'AADSTS70000: Unknown refresh token.',
                                  [70000])
            if state.mode == 'interaction_required':
                return self.interaction_required()
            return self.user_tokens(grant, tenant, scope, mode=state.mode)

        if grant == 'client_credentials':
            if state.mode == 'expired_secret':
                return self.error(
                    401, 'invalid_client',
                    'AADSTS7000222: The provided client secret keys are expired.', [7000222])
            if form.get('client_id') != state.app_id or \
                    form.get('client_secret') != state.app_secret or state.mode == 'bad_secret':
                return self.error(
                    401, 'invalid_client',
                    'AADSTS7000215: Invalid client secret provided.', [7000215])
            return self.application_token(grant, tenant, scope, mode=state.mode)

        return self.error(400, 'unsupported_grant_type', 'AADSTS70003: Unsupported grant.', [70003])

    # ---- responses ------------------------------------------------------------------------

    def error(self, status, code, description, error_codes, **extra):
        body = {
            'error': code,
            'error_description': description + '\r\nTrace ID: 0\r\nCorrelation ID: 0',
            'error_codes': error_codes,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime()),
            'trace_id': '00000000-0000-0000-0000-000000000000',
            'correlation_id': '00000000-0000-0000-0000-000000000001',
        }
        body.update(extra)
        self.send_json(status, body)

    def interaction_required(self):
        self.error(400, 'invalid_grant',
                   'AADSTS50076: Due to a configuration change, you must use multi-factor '
                   'authentication to access this resource.', [50076], suberror='basic_action')

    def access_token(self, tenant, scope, mode, user):
        state = self.fake.state
        factory = self.fake.factory
        if mode == 'opaque_token':
            text = factory.opaque_token()
        else:
            key = (tenant, scope, user)
            if mode == 'same_token' and key in state.last_access_token:
                return state.last_access_token[key]
            now = state.now() - (3600 if mode == 'stale_token' else 0)
            audience = resource_of(scope.split()[0]) if scope else ''
            if user:
                text = factory.access_token(audience, tenant, state.user_oid, now, state.groups,
                                            upn=state.username)
            else:
                text = factory.access_token(audience, tenant, state.app_oid, now, [],
                                            app_id=state.app_id)
            state.last_access_token[key] = text
        return text

    def user_tokens(self, grant, tenant, scope, mode):
        state = self.fake.state
        factory = self.fake.factory
        with state.lock:
            access = self.access_token(tenant, scope, mode, user=True)
            refresh = factory.refresh_token()
            state.refresh_tokens.add(refresh)
            identity = factory.id_token(tenant, state.user_oid, state.username, state.now())
            state.record_issued(grant, tenant, scope, 'access', access)
            state.record_issued(grant, tenant, scope, 'refresh', refresh)
            state.record_issued(grant, tenant, scope, 'id', identity)
        self.send_json(200, {
            'token_type': 'Bearer',
            'scope': scope,
            'expires_in': tokens.LIFETIME_SECONDS,
            'ext_expires_in': tokens.LIFETIME_SECONDS,
            'access_token': access,
            'refresh_token': refresh,
            'id_token': identity,
            # As in the real service, the home tenant identifies the account whatever tenant the token is for.
            'client_info': tokens.client_info(state.user_oid, state_module.HOME_TENANT),
        })

    def application_token(self, grant, tenant, scope, mode):
        state = self.fake.state
        with state.lock:
            access = self.access_token(tenant, scope, mode, user=False)
            state.record_issued(grant, tenant, scope, 'access', access)
        self.send_json(200, {
            'token_type': 'Bearer',
            'scope': scope,
            'expires_in': tokens.LIFETIME_SECONDS,
            'ext_expires_in': tokens.LIFETIME_SECONDS,
            'access_token': access,
        })


class FakeEntra:
    """The fake identity provider. ``start()`` returns once it listens; ``stop()`` shuts it down."""

    def __init__(self, directory):
        self.state = state_module.State()
        self.factory = tokens.TokenFactory()
        self.ca_path, self._server_path, self._key_path = certs.create(directory)
        self.base_url = None
        self._server = None
        self._thread = None

    def start(self):
        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self._server.daemon_threads = True
        self._server.fake = self
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self._server_path), str(self._key_path))
        self._server.socket = context.wrap_socket(self._server.socket, server_side=True)
        self.base_url = 'https://127.0.0.1:{}'.format(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.base_url

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5)
            self._server = None

    def metadata(self):
        """The Azure Resource Manager cloud metadata, in the shapes the Azure CLI reads."""
        return {
            'name': 'FakeEntra',
            'authentication': {
                'loginEndpoint': self.base_url,
                'audiences': [RESOURCES['active_directory_resource_id']],
            },
            'resourceManager': self.base_url + '/',
            'graphAudience': RESOURCES['active_directory_graph_resource_id'],
            'graph': 'https://graph.example.test/',
            'microsoftGraphResourceId': RESOURCES['microsoft_graph_resource_id'],
            'batch': RESOURCES['batch_resource_id'],
            'media': RESOURCES['media_resource_id'],
            'ossrdbmsResourceId': RESOURCES['ossrdbms_resource_id'],
            'activeDirectoryDataLake': RESOURCES['active_directory_data_lake_resource_id'],
            'galleryEndpoint': 'https://gallery.example.test/',
            'suffixes': {},
        }

    def cloud_config(self):
        """The JSON for ``az cloud register --cloud-config``."""
        return {
            'endpoints': {
                'resourceManager': self.base_url,
                'activeDirectory': self.base_url,
                'activeDirectoryResourceId': RESOURCES['active_directory_resource_id'],
                'management': RESOURCES['active_directory_resource_id'],
                'activeDirectoryGraphResourceId': RESOURCES['active_directory_graph_resource_id'],
                'microsoftGraphResourceId': RESOURCES['microsoft_graph_resource_id'],
                'batchResourceId': RESOURCES['batch_resource_id'],
                'mediaResourceId': RESOURCES['media_resource_id'],
                'ossrdbmsResourceId': RESOURCES['ossrdbms_resource_id'],
                'activeDirectoryDataLakeResourceId':
                    RESOURCES['active_directory_data_lake_resource_id'],
            },
            'suffixes': {},
        }
