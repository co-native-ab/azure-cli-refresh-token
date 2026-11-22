# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------

"""Telling whether a token is new.

This module is pure: it uses only the standard library and does no network, file system, clock or
Azure CLI access; times are passed in. A token is only ever hashed or has its payload decoded here.
The header and the signature are never decoded and never kept.
"""

import base64
import hashlib
import json
from collections import namedtuple

# Microsoft Entra ID sets a token's issue time a few minutes before it issues the token, and clocks
# differ, so "issued after the command started" allows this many seconds for the proof. A token that
# is older still cannot pass, because it must also differ from the token the command started with.
ALLOWANCE_SECONDS = 600

# Issue times are whole seconds, and the two tokens a run compares may come from different servers
# of the identity provider, whose clocks can differ by a second or so. The label allows this many
# seconds on top of the run time.
LABEL_MARGIN_SECONDS = 5

FINGERPRINT_LENGTH = 12

VERDICT_UNREADABLE = 'unreadable'
VERDICT_SAME = 'same'
VERDICT_STALE = 'stale'
VERDICT_PROVEN = 'proven'

LABEL_ISSUED = 'issued'
LABEL_REFRESHED = 'refreshed'

STEP_SUCCEED = 'succeed'
STEP_RENEW_BROKER = 'renew_broker'
STEP_FAIL = 'fail'

_CP1_CLAIMS = '{"access_token": {"xms_cc": {"values": ["CP1"]}}}'

TokenFacts = namedtuple('TokenFacts', ['fingerprint', 'iat', 'aud', 'tid', 'exp', 'claims'])


def fingerprint(token):
    """The first characters of the token's SHA-256 hash: the only identity of a token that leaves
    the process."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()[:FINGERPRINT_LENGTH]


def _decode_payload(token):
    segments = token.split('.')
    if len(segments) != 3:
        return None
    payload = segments[1]
    try:
        raw = base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4))
        decoded = json.loads(raw.decode('utf-8'))
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _integer(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def inspect(token):
    """The facts about a token: its fingerprint and what its payload says.

    ``iat`` is None unless the token has three segments and a JSON payload holding an integer ``iat``.
    """
    claims = _decode_payload(token)
    if claims is None:
        return TokenFacts(fingerprint(token), None, None, None, None, {})
    audience = claims.get('aud')
    if isinstance(audience, list):
        audience = audience[0] if audience else None
    return TokenFacts(
        fingerprint=fingerprint(token),
        iat=_integer(claims.get('iat')),
        aud=audience,
        tid=claims.get('tid'),
        exp=_integer(claims.get('exp')),
        claims=claims,
    )


def prove(start_facts, final_facts, start, allowance=ALLOWANCE_SECONDS):
    """Decide whether the token now in use is a new one.

    It counts only if it differs from the starting token and was issued no earlier than the start
    time minus the allowance.
    """
    if start_facts.iat is None or final_facts.iat is None:
        return VERDICT_UNREADABLE
    if final_facts.fingerprint == start_facts.fingerprint:
        return VERDICT_SAME
    if final_facts.iat < start - allowance:
        return VERDICT_STALE
    return VERDICT_PROVEN


def label(start_facts, final_facts, elapsed, margin=LABEL_MARGIN_SECONDS):
    """``issued`` when the starting token was itself obtained during this run, else ``refreshed``.

    Both issue times come from the identity provider, which dates them the same way, so its early
    dating cancels out and the local clock plays no part. A starting token obtained during the run
    was issued at most ``elapsed`` seconds before the new one, so the label is ``issued`` when the
    two issue times differ by no more than ``elapsed`` plus ``margin`` seconds. If either issue time
    is unreadable the label is ``refreshed``. The label never decides whether a new token is
    requested.
    """
    if start_facts.iat is None or final_facts.iat is None:
        return LABEL_REFRESHED
    if abs(final_facts.iat - start_facts.iat) <= elapsed + margin:
        return LABEL_ISSUED
    return LABEL_REFRESHED


def next_step(verdict, broker_in_use, broker_tried):
    """What to do after a proof: finish, renew the token in the broker once, or give up."""
    if verdict == VERDICT_PROVEN:
        return STEP_SUCCEED
    if verdict in (VERDICT_SAME, VERDICT_STALE) and broker_in_use and not broker_tried:
        return STEP_RENEW_BROKER
    return STEP_FAIL


def broker_claims(cp1_disabled):
    """The claims the Azure CLI's MSAL sends to the broker for an empty claims challenge.

    They are the client capabilities, unless the Azure CLI was told to leave them out.
    """
    return None if cp1_disabled else _CP1_CLAIMS
