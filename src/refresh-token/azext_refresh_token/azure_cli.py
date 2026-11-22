# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------

"""The thin layer that talks to the Azure CLI.

It makes no decisions. It reads the token ``az account get-access-token`` would return and asks the
Azure CLI's own credential for a new one. Tokens exist here only as local values: they are never
logged, stored or put in an exception.
"""

# ``Profile`` is published by the Azure CLI only in this module. Microsoft's own extensions import
# it from here too. The name and the methods used below are public.
from azure.cli.core._profile import Profile

from azext_refresh_token import selection

# An empty claims challenge makes MSAL skip the access token it has cached and ask for a new one.
EMPTY_CLAIMS = '{}'


class CurrentToken:  # pylint: disable=too-few-public-methods
    """A token as ``get-access-token`` returns it. Its text is kept out of ``repr``."""

    __slots__ = ('token', 'tenant', 'subscription', 'expires_on')

    def __init__(self, token, tenant, subscription, expires_on):
        self.token = token
        self.tenant = tenant
        self.subscription = subscription
        self.expires_on = expires_on

    def __repr__(self):
        return f'CurrentToken(tenant={self.tenant!r}, subscription={self.subscription!r})'


def get_profile(cli_ctx):
    return Profile(cli_ctx=cli_ctx)


def get_account(profile, subscription):
    """The account the Azure CLI would use. It raises the Azure CLI's own error when nobody is
    signed in or the subscription is unknown."""
    return profile.get_subscription(subscription)


def current_token(profile, resource, scopes, subscription, tenant):
    """The token ``az account get-access-token`` returns now for the same arguments.

    Without a cached token the Azure CLI gets one from Microsoft Entra ID.
    """
    raw, subscription_id, tenant_id = profile.get_raw_token(
        resource=resource, scopes=scopes, subscription=subscription, tenant=tenant)
    return CurrentToken(raw[1], tenant_id, subscription_id, raw[2]['expires_on'])


def force_new_token(profile, account, scopes, subscription, tenant):
    """Ask the Azure CLI's credential for a new token with an empty claims challenge.

    The Azure CLI stores the answer where later ``get-access-token`` calls find it. The token
    itself is dropped here.
    """
    if selection.is_other_tenant(tenant, account['tenantId']):
        credential = profile.get_login_credentials(
            subscription_id=subscription, aux_tenants=[tenant])[0]
        credential.get_auxiliary_tokens(*scopes, claims_challenge=EMPTY_CLAIMS)
        return
    credential = profile.get_login_credentials(subscription_id=subscription)[0]
    credential.get_token(*scopes, claims=EMPTY_CLAIMS)
