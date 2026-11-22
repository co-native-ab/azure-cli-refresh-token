"""Test tokens for the fake identity provider.

Access tokens are HS256 JSON Web Tokens signed with a per-run random key. Neither the Azure CLI nor
MSAL verifies the signature of an access token, so a shared-secret signature is enough. Test tooling
only.
"""

import base64
import hashlib
import hmac
import json
import secrets

AZURE_CLI_CLIENT_ID = '04b07795-8ddb-461a-bbee-02f9e1bf7b46'
LIFETIME_SECONDS = 3600
# Microsoft Entra ID sets the issue time of a token a few minutes before it issues the token. The
# fake does the same so the proof's allowance is exercised.
BACKDATE_SECONDS = 300


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _segment(value):
    return _b64(json.dumps(value, separators=(',', ':')).encode('utf-8'))


class TokenFactory:
    def __init__(self):
        self._key = secrets.token_bytes(32)

    def sign(self, claims):
        signing_input = '{}.{}'.format(_segment({'alg': 'HS256', 'typ': 'JWT'}), _segment(claims))
        signature = hmac.new(self._key, signing_input.encode('ascii'), hashlib.sha256).digest()
        return '{}.{}'.format(signing_input, _b64(signature))

    def access_token(self, audience, tenant, oid, now, groups, upn=None, app_id=None):
        """An access token whose issue time is ``now`` minus the backdating."""
        issued = int(now) - BACKDATE_SECONDS
        claims = {
            'aud': audience,
            'iss': 'https://sts.example.test/{}/'.format(tenant),
            'iat': issued,
            'nbf': issued,
            'exp': issued + LIFETIME_SECONDS + BACKDATE_SECONDS,
            'tid': tenant,
            'oid': oid,
            'sub': oid,
            'ver': '1.0',
            'uti': secrets.token_urlsafe(16),
        }
        if upn:
            claims['upn'] = upn
            claims['groups'] = list(groups)
        if app_id:
            claims['appid'] = app_id
        return self.sign(claims)

    def id_token(self, tenant, oid, username, now):
        return self.sign({
            'aud': AZURE_CLI_CLIENT_ID,
            'iss': 'https://login.example.test/{}/v2.0'.format(tenant),
            'iat': int(now),
            'nbf': int(now),
            'exp': int(now) + LIFETIME_SECONDS,
            'tid': tenant,
            'oid': oid,
            'sub': oid,
            'preferred_username': username,
            'name': 'Test User',
            'ver': '2.0',
        })

    @staticmethod
    def opaque_token():
        """An access token that is not a JSON Web Token."""
        return 'opaque-' + secrets.token_urlsafe(32)

    @staticmethod
    def refresh_token():
        return 'refresh-' + secrets.token_urlsafe(32)


def client_info(oid, tenant):
    return _b64(json.dumps({'uid': oid, 'utid': tenant}).encode('utf-8'))
