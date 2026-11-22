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

from azext_refresh_token import azure_cli, broker, proof, result, selection

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
            error.error_msg, recommendation=_sign_in_recommendation(request)) from error
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


def _sign_in_recommendation(request):
    return result.sign_in_required_recommendation(
        request.kind, request.tenant or request.account['tenantId'], request.scopes_used,
        request.username)


def _current_token(request):
    return azure_cli.current_token(
        request.profile, request.resource, request.scopes, request.subscription, request.tenant)


def _refresh(cmd, request, start, show_claims):
    starting = _current_token(request)
    starting_token = starting.token
    start_facts = proof.inspect(starting_token)
    if start_facts.iat is None:
        raise CLIError(result.cannot_prove_message())
    logger.info('Starting token %s for scopes %s', start_facts.fingerprint, request.scopes_used)

    use_broker = selection.broker_in_use(
        sys.platform, platform.machine(), request.kind,
        cmd.cli_ctx.config.getboolean('core', 'enable_broker_on_windows', fallback=True),
        cmd.cli_ctx.config.getboolean('core', 'enable_broker_on_mac', fallback=False))
    broker_tried = False

    while True:
        azure_cli.force_new_token(request.profile, request.account, request.scopes_used,
                                  request.subscription, request.tenant)
        final = _current_token(request)
        final_facts = proof.inspect(final.token)
        verdict = proof.prove(start_facts, final_facts, start)
        logger.info('New token %s: %s', final_facts.fingerprint, verdict)
        step = proof.next_step(verdict, use_broker, broker_tried)
        if step == proof.STEP_SUCCEED:
            break
        if step == proof.STEP_FAIL:
            raise CLIError(_not_renewed_message(verdict, final_facts, use_broker))
        _renew_in_broker(cmd, request, start_facts, starting_token)
        broker_tried = True

    return result.build(
        proof.label(start_facts, start), request.scopes_used, final_facts, tenant=final.tenant,
        subscription=final.subscription, start_fingerprint=start_facts.fingerprint,
        expires_on=final.expires_on, show_claims=show_claims)


def _renew_in_broker(cmd, request, start_facts, token_to_renew):
    """Make the broker drop the token it holds for these scopes and issue a new one.

    The Azure CLI's own cache sits in front of the broker, so the caller asks the credential for a
    token again afterwards, which stores what the broker now returns.
    """
    setting = selection.broker_setting(sys.platform)
    try:
        import pymsalruntime  # pylint: disable=import-outside-toplevel
    except ImportError as error:
        # MSAL cannot use the broker without this library either, so the credential path was not
        # served by the broker; this only explains why the refresh could not be proven.
        raise CLIError(result.broker_unavailable_message(
            setting, f'the broker library is not available ({error})')) from error
    active_directory = cmd.cli_ctx.cloud.endpoints.active_directory.rstrip('/')
    authority = f'{active_directory}/{start_facts.tid}'
    claims = proof.broker_claims(bool(os.environ.get('AZURE_IDENTITY_DISABLE_CP1')))
    logger.info('Renewing the token in the broker for scopes %s', request.scopes_used)
    renewal = broker.BrokerRenewal(pymsalruntime, AZURE_CLI_CLIENT_ID)
    try:
        renewal.renew(authority, request.username, request.scopes_used, claims=claims,
                      token_to_renew=token_to_renew, platform=sys.platform)
    except broker.BrokerAccountError as error:
        raise CLIError(result.broker_account_message(setting, error.found)) from error
    except broker.BrokerInteractionRequired:
        raise
    except broker.BrokerFailure as error:
        raise CLIError(result.broker_unavailable_message(setting, str(error))) from error


def _not_renewed_message(verdict, final_facts, use_broker):
    if verdict == proof.VERDICT_SAME:
        message = result.not_renewed_same_message(final_facts.fingerprint)
    elif verdict == proof.VERDICT_STALE:
        message = result.not_renewed_stale_message(final_facts.iat)
    else:
        return result.cannot_prove_message()
    if use_broker:
        message += ' ' + result.broker_sentence(selection.broker_setting(sys.platform))
    return message
