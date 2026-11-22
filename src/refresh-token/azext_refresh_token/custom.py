# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------

import os
import platform
import sys
import time

from azure.cli.core.azclierror import AuthenticationError
from azure.cli.core.auth.constants import AZURE_CLI_CLIENT_ID
from azure.cli.core.util import in_cloud_console
from knack.log import get_logger
from knack.util import CLIError

from azext_refresh_token import azure_cli, broker, proof, result, selection

logger = get_logger(__name__)


def refresh_token(cmd, resource_type=None, resource=None, scopes=None, tenant=None,
                  subscription=None, show_claims=False):
    start = time.time()

    try:
        selection.check_conflicts(subscription, tenant)
    except ValueError as error:
        raise CLIError(str(error))

    profile = azure_cli.get_profile(cmd.cli_ctx)
    account = azure_cli.get_account(profile, subscription)
    kind = selection.account_kind(account, in_cloud_console())
    if not selection.is_supported(kind):
        raise CLIError(result.unsupported_account_message(kind))

    endpoints = cmd.cli_ctx.cloud.endpoints
    resource = selection.resolve_resource(resource, resource_type, endpoints)
    scopes_used = selection.resolve_scopes(scopes, resource, endpoints.active_directory_resource_id)
    account_tenant = account['tenantId']
    username = account['user']['name']

    def sign_in_recommendation():
        return result.sign_in_required_recommendation(
            kind, tenant or account_tenant, scopes_used, username)

    try:
        starting = azure_cli.current_token(profile, resource, scopes, subscription, tenant)
        starting_token = starting.token
        start_facts = proof.inspect(starting_token)
        if start_facts.iat is None:
            raise CLIError(result.cannot_prove_message())
        logger.info('Starting token %s for scopes %s', start_facts.fingerprint, scopes_used)

        use_broker = selection.broker_in_use(
            sys.platform, platform.machine(), kind,
            cmd.cli_ctx.config.getboolean('core', 'enable_broker_on_windows', fallback=True),
            cmd.cli_ctx.config.getboolean('core', 'enable_broker_on_mac', fallback=False))
        broker_tried = False

        while True:
            azure_cli.force_new_token(profile, account, scopes_used, subscription, tenant)
            final = azure_cli.current_token(profile, resource, scopes, subscription, tenant)
            final_facts = proof.inspect(final.token)
            verdict = proof.prove(start_facts, final_facts, start)
            logger.info('New token %s: %s', final_facts.fingerprint, verdict)
            step = proof.next_step(verdict, use_broker, broker_tried)
            if step == proof.STEP_SUCCEED:
                break
            if step == proof.STEP_FAIL:
                raise CLIError(_not_renewed_message(verdict, final_facts, use_broker))
            _renew_in_broker(cmd, start_facts, scopes_used, username, starting_token)
            broker_tried = True
    except AuthenticationError as error:
        raise AuthenticationError(error.error_msg, recommendation=sign_in_recommendation())
    except broker.BrokerInteractionRequired as error:
        raise AuthenticationError(str(error), recommendation=sign_in_recommendation())

    label = proof.label(start_facts, start)
    return result.build(label, scopes_used, final_facts, final.tenant, final.subscription,
                        start_facts.fingerprint, final.expires_on, show_claims)


def _renew_in_broker(cmd, start_facts, scopes_used, username, token_to_renew):
    """Make the broker drop the token it holds for these scopes and issue a new one.

    The Azure CLI's own cache sits in front of the broker, so the caller asks the credential for a
    token again afterwards, which stores what the broker now returns.
    """
    setting = _broker_setting()
    try:
        import pymsalruntime
    except ImportError as error:
        # MSAL cannot use the broker without this library either, so the credential path above was
        # not served by the broker; this only explains why the refresh could not be proven.
        raise CLIError(result.broker_unavailable_message(
            setting, 'the broker library is not available ({})'.format(error)))
    tenant_id = start_facts.tid
    authority = '{}/{}'.format(cmd.cli_ctx.cloud.endpoints.active_directory.rstrip('/'), tenant_id)
    claims = proof.broker_claims(bool(os.environ.get('AZURE_IDENTITY_DISABLE_CP1')))
    logger.info('Renewing the token in the broker for scopes %s', scopes_used)
    renewal = broker.BrokerRenewal(pymsalruntime, AZURE_CLI_CLIENT_ID)
    try:
        renewal.renew(authority, username, scopes_used, claims, token_to_renew, sys.platform)
    except broker.BrokerAccountError as error:
        raise CLIError(result.broker_account_message(setting, error.found))
    except broker.BrokerFailure as error:
        raise CLIError(result.broker_unavailable_message(setting, str(error)))


def _broker_setting():
    return selection.broker_setting(sys.platform)


def _not_renewed_message(verdict, final_facts, use_broker):
    if verdict == proof.VERDICT_SAME:
        message = result.not_renewed_same_message(final_facts.fingerprint)
    elif verdict == proof.VERDICT_STALE:
        message = result.not_renewed_stale_message(final_facts.iat)
    else:
        return result.cannot_prove_message()
    if use_broker:
        message += ' ' + result.broker_sentence(_broker_setting())
    return message
