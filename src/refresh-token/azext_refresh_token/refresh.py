# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------

"""The sequence of one refresh: force a new token, prove it, renew in the broker once if needed.

Nothing here touches the Azure CLI or a broker library. The caller passes in the functions that do,
so the whole sequence can be tested without either. Tokens are only handed from one function to
another here; they are never logged or put in a message.
"""

from azext_refresh_token import broker, proof, result


class RefreshError(Exception):
    """The refresh could not be proven or the broker could not renew; the message says what to do."""


def run(*, start, current, force, renew, use_broker, setting, log=lambda *_: None):
    """Refresh until a new token is proven, or fail.

    ``start`` is the time the command started. ``current()`` returns the token the Azure CLI hands
    out now (an object with a ``token`` attribute), ``force()`` makes the Azure CLI's credential ask
    for a new one, and ``renew(token, tenant_id)`` makes the broker drop ``token`` and issue a new
    one. Returns the starting token's facts, the token now in use and its facts.
    """
    starting = current()
    start_facts = proof.inspect(starting.token)
    if start_facts.iat is None:
        raise RefreshError(result.cannot_prove_message())
    log('Starting token %s', start_facts.fingerprint)

    broker_tried = False
    while True:
        force()
        final = current()
        final_facts = proof.inspect(final.token)
        verdict = proof.prove(start_facts, final_facts, start)
        log('New token %s: %s', final_facts.fingerprint, verdict)
        step = proof.next_step(verdict, use_broker, broker_tried)
        if step == proof.STEP_SUCCEED:
            return start_facts, final, final_facts
        if step == proof.STEP_FAIL:
            raise RefreshError(_not_renewed_message(verdict, final_facts, use_broker, setting))
        # The broker renews the token the forced request returned: that is the one it holds for
        # this request, and it is the starting token unless the credential returned another one.
        if final_facts.tid is None:
            raise RefreshError(result.broker_unavailable_message(
                setting, 'the token to renew has no readable tenant id'))
        renew(final.token, final_facts.tid)
        broker_tried = True


def renew_in_broker(token, tenant_id, *, load_module, client_id, active_directory, username,
                    scopes, claims, platform, setting):
    """Make the broker drop ``token`` and issue a new one for these scopes.

    ``load_module()`` returns the ``pymsalruntime`` module and raises ImportError without it.
    Broker failures become a ``RefreshError`` naming the setting that turns the broker off; a
    broker that needs the user to sign in again raises ``BrokerInteractionRequired`` unchanged.
    """
    try:
        module = load_module()
    except ImportError as error:
        # MSAL cannot use the broker without this library either, so the credential path was not
        # served by the broker; this only explains why the refresh could not be proven.
        raise RefreshError(result.broker_unavailable_message(
            setting, f'the broker library is not available ({error})')) from error
    authority = f'{active_directory.rstrip("/")}/{tenant_id}'
    renewal = broker.BrokerRenewal(module, client_id)
    try:
        renewal.renew(authority, username, scopes, claims=claims, token_to_renew=token,
                      platform=platform)
    except broker.BrokerAccountError as error:
        raise RefreshError(result.broker_account_message(setting, error.found)) from error
    except broker.BrokerInteractionRequired:
        raise
    except broker.BrokerFailure as error:
        raise RefreshError(result.broker_unavailable_message(setting, str(error))) from error


def _not_renewed_message(verdict, final_facts, use_broker, setting):
    if verdict == proof.VERDICT_SAME:
        message = result.not_renewed_same_message(final_facts.fingerprint)
    elif verdict == proof.VERDICT_STALE:
        message = result.not_renewed_stale_message(final_facts.iat)
    else:
        return result.new_token_unreadable_message(final_facts.fingerprint)
    if use_broker:
        message += ' ' + result.broker_sentence(setting)
    return message
