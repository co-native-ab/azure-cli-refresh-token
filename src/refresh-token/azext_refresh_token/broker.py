# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------

"""Renewing a token in the operating system broker (Windows, macOS) through ``pymsalruntime``.

This is a thin layer: it makes no decisions. The ``pymsalruntime`` module is passed in, so tests can
hand it a stand-in. Only silent calls are used: nothing here can show a window or ask the user for
anything. The renewed token is never read; the caller makes the Azure CLI fetch it afterwards.
"""

import threading
import uuid

DEFAULT_REDIRECT_URI = 'https://login.microsoftonline.com/common/oauth2/nativeclient'
MAC_REDIRECT_URI = 'msauth.com.msauth.unsignedapp://auth'
DEFAULT_TIMEOUT_SECONDS = 60


class BrokerFailure(Exception):
    """The broker call failed or did not answer in time."""


class BrokerInteractionRequired(BrokerFailure):
    """The broker needs the user to sign in again."""


class BrokerAccountError(BrokerFailure):
    """The broker knows no account, or several, with the signed-in user name."""

    def __init__(self, found):
        super().__init__('the broker knows {} accounts with the signed-in user name'.format(found))
        self.found = found


class BrokerRenewal:
    def __init__(self, module, client_id, timeout=DEFAULT_TIMEOUT_SECONDS):
        self._module = module
        self._client_id = client_id
        self._timeout = timeout

    def renew(self, authority, username, scopes, claims, token_to_renew, platform):
        """Make the broker drop ``token_to_renew`` and issue a new token for the same request."""
        account = self._find_account(username)

        parameters = self._module.MSALRuntimeAuthParameters(self._client_id, authority)
        parameters.set_requested_scopes(list(scopes))
        parameters.set_redirect_uri(MAC_REDIRECT_URI if platform == 'darwin' else DEFAULT_REDIRECT_URI)
        if claims:
            parameters.set_decoded_claims(claims)
        parameters.set_access_token_to_renew(token_to_renew)

        outcome = self._wait(lambda callback: self._module.acquire_token_silently(
            parameters, str(uuid.uuid4()), account, callback))
        self._check(outcome.get_error())

    def _find_account(self, username):
        outcome = self._wait(lambda callback: self._module.discover_accounts(
            self._client_id, str(uuid.uuid4()), callback))
        self._check(outcome.get_error())
        matches = [account for account in outcome.get_accounts()
                   if (account.get_user_name() or '').lower() == username.lower()]
        if len(matches) != 1:
            raise BrokerAccountError(len(matches))
        return matches[0]

    def _wait(self, start):
        """Start an asynchronous broker call and wait for its callback."""
        done = threading.Event()
        answers = []

        def callback(answer):
            answers.append(answer)
            done.set()

        handle = start(callback)
        if not done.wait(self._timeout):
            handle.cancel_async_operation()
            raise BrokerFailure('the broker did not answer within {} seconds'.format(self._timeout))
        return answers[0]

    def _check(self, error):
        if error is None:
            return
        status = error.get_status()
        if status == self._module.Response_Status.Status_InteractionRequired:
            raise BrokerInteractionRequired(
                'The broker needs you to sign in again (error code {}).'.format(
                    error.get_error_code()))
        raise BrokerFailure('the broker returned an error (status {}, error code {})'.format(
            status, error.get_error_code()))
