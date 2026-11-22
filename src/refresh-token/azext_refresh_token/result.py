# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------

"""The command's output and its error messages.

This module is pure: it uses only the standard library. Nothing here receives a token. Callers pass
fingerprints, times and decoded values only, so no message can contain one.
"""

import datetime

from azext_refresh_token.proof import ALLOWANCE_SECONDS
from azext_refresh_token.selection import KIND_SERVICE_PRINCIPAL


def _iso_utc(epoch_seconds):
    moment = datetime.datetime.fromtimestamp(epoch_seconds, datetime.timezone.utc)
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def build(label, scopes, final_facts, *, tenant, subscription, start_fingerprint, expires_on,
          show_claims):
    """The JSON object the command returns."""
    output = {
        'status': label,
        'scopes': list(scopes),
        'audience': final_facts.aud,
        'tenant': tenant,
    }
    if subscription is not None:
        output['subscription'] = subscription
    output['previousFingerprint'] = start_fingerprint
    output['fingerprint'] = final_facts.fingerprint
    output['issuedAt'] = _iso_utc(final_facts.iat)
    output['expiresOn'] = _iso_utc(expires_on)
    output['expires_on'] = int(expires_on)
    if show_claims:
        output['claims'] = final_facts.claims
    return output


def unsupported_account_message(kind):
    """The account cannot have its tokens refreshed by this extension; nothing was requested."""
    names = {
        'managedIdentity': 'a managed identity',
        'cloudShell': 'a Cloud Shell account',
    }
    what = names.get(kind, 'this type of account')
    return (f'The signed-in account is {what}, whose tokens cannot be refreshed by this extension. '
            'Nothing was requested from Microsoft Entra ID.')


def login_command(kind, tenant, scopes, username):
    """The ``az login`` command that signs the account in again."""
    if kind == KIND_SERVICE_PRINCIPAL:
        return f'az login --service-principal --username "{username}" --tenant "{tenant}"'
    parts = [f'az login --tenant "{tenant}"']
    if scopes:
        parts.append('--scope ' + ' '.join(f'"{scope}"' for scope in scopes))
    return ' '.join(parts)


def sign_in_required_recommendation(kind, tenant, scopes, username):
    """What to do when Microsoft Entra ID needs the user to sign in again."""
    return ('Sign in again with the command below; additional arguments may be added as needed:\n'
            + login_command(kind, tenant, scopes, username))


def not_renewed_same_message(fingerprint):
    """The Azure CLI still returns the token it had."""
    return ('The token was not renewed: the Azure CLI still returns the same token '
            f'(fingerprint {fingerprint}).')


def not_renewed_stale_message(issued_at):
    """The new token was issued before the command started."""
    return ('The token was not renewed: the token the Azure CLI returns now was issued at '
            f'{_iso_utc(issued_at)}, before the command started (allowing '
            f'{ALLOWANCE_SECONDS // 60} minutes). If the clock of this machine is wrong, correct '
            'it and try again.')


def cannot_prove_message():
    """The token has no readable issue time, so a refresh could not be proven."""
    return ('A refresh cannot be proven for this token because it has no readable issue time '
            '(it is not a JSON Web Token). Nothing was requested from Microsoft Entra ID.')


def broker_sentence(setting):
    """How to avoid the broker, naming the setting without changing it."""
    return ('The Azure CLI uses a broker for this account. To avoid the broker, run '
            f'`az config set {setting}=false` and then `az login`. This command does not change '
            'the setting.')


def broker_unavailable_message(setting, detail):
    """The broker library is missing or the broker call failed or timed out."""
    return f'The broker could not renew the token: {detail}. {broker_sentence(setting)}'


def broker_account_message(setting, found):
    """The broker knows no account, or several, with the signed-in user name."""
    if found == 0:
        problem = 'the broker knows no account with the signed-in user name'
    else:
        problem = 'the broker knows several accounts with the signed-in user name'
    return f'The broker could not renew the token: {problem}. {broker_sentence(setting)}'
