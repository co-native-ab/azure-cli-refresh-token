# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------

import os
import platform
import sys
import time
from collections import namedtuple

from azure.cli.core.azclierror import AuthenticationError
from azure.cli.core.auth.constants import AZURE_CLI_CLIENT_ID
from azure.cli.core.util import in_cloud_console
from knack.log import get_logger
from knack.util import CLIError

from azext_refresh_token import azure_cli, broker, proof, refresh, result, selection

logger = get_logger(__name__)

# What one run refreshes, resolved from the arguments and the account.
Request = namedtuple('Request', [
    'profile', 'account', 'kind', 'resource', 'scopes', 'scopes_used', 'subscription', 'tenant',
    'username'])


def refresh_token(cmd, resource_type=None, resource=None, scopes=None, tenant=None,  # pylint: disable=too-many-positional-arguments
                  subscription=None, show_claims=False):
    start = time.time()
    request = _resolve_request(cmd, resource_type, resource, scopes, tenant, subscription)
    try:
        return _refresh(cmd, request, start, show_claims)
    except AuthenticationError as error:
        raise AuthenticationError(
            error.error_msg, recommendation=_recommendations(request, error)) from error
    except broker.BrokerInteractionRequired as error:
        raise AuthenticationError(
            str(error), recommendation=_sign_in_recommendation(request)) from error


def _resolve_request(cmd, resource_type, resource, scopes, tenant, subscription):  # pylint: disable=too-many-positional-arguments
    try:
        selection.check_conflicts(subscription, tenant)
    except ValueError as error:
        raise CLIError(str(error)) from error

    profile = azure_cli.get_profile(cmd.cli_ctx)
    account = azure_cli.get_account(profile, subscription)
    kind = selection.account_kind(account, in_cloud_console())
    if not selection.is_supported(kind):
        raise CLIError(result.unsupported_account_message(kind))

    endpoints = cmd.cli_ctx.cloud.endpoints
    resource = selection.resolve_resource(resource, resource_type, endpoints)
    scopes_used = selection.resolve_scopes(scopes, resource, endpoints.active_directory_resource_id)
    return Request(profile, account, kind, resource, scopes, scopes_used, subscription, tenant,
                   account['user']['name'])


def _recommendations(request, error):
    """The Azure CLI's own recommendation for a service principal (for example an expired secret)
    stays; ours is added. For a user the Azure CLI's advice is to sign out first, which is not
    needed, so only ours is shown."""
    kept = []
    if request.kind == selection.KIND_SERVICE_PRINCIPAL:
        kept = list(getattr(error, 'recommendations', None) or [])
    return kept + [_sign_in_recommendation(request)]


def _sign_in_recommendation(request):
    return result.sign_in_required_recommendation(
        request.kind, request.tenant or request.account['tenantId'], request.scopes_used,
        request.username)


def _current_token(request):
    return azure_cli.current_token(
        request.profile, request.resource, request.scopes, request.subscription, request.tenant)


def _refresh(cmd, request, start, show_claims):
    use_broker = selection.broker_in_use(
        sys.platform, platform.machine(), request.kind,
        cmd.cli_ctx.config.getboolean('core', 'enable_broker_on_windows', fallback=True),
        cmd.cli_ctx.config.getboolean('core', 'enable_broker_on_mac', fallback=False))
    setting = selection.broker_setting(sys.platform)
    claims = proof.broker_claims(bool(os.environ.get('AZURE_IDENTITY_DISABLE_CP1')))

    def renew(token, tenant_id):
        logger.info('Renewing the token in the broker for scopes %s', request.scopes_used)
        refresh.renew_in_broker(
            token, tenant_id, load_module=_load_broker_library, client_id=AZURE_CLI_CLIENT_ID,
            active_directory=cmd.cli_ctx.cloud.endpoints.active_directory,
            username=request.username, scopes=request.scopes_used, claims=claims,
            platform=sys.platform, setting=setting)

    try:
        start_facts, final, final_facts = refresh.run(
            start=start, current=lambda: _current_token(request),
            force=lambda: azure_cli.force_new_token(
                request.profile, request.account, request.scopes_used, request.subscription,
                request.tenant),
            renew=renew, use_broker=use_broker, setting=setting, log=logger.info)
    except refresh.RefreshError as error:
        raise CLIError(str(error)) from error

    return result.build(
        proof.label(start_facts, start), request.scopes_used, final_facts, tenant=final.tenant,
        subscription=final.subscription, start_fingerprint=start_facts.fingerprint,
        expires_on=final.expires_on, show_claims=show_claims)


def _load_broker_library():
    import pymsalruntime  # pylint: disable=import-outside-toplevel,import-error
    return pymsalruntime
