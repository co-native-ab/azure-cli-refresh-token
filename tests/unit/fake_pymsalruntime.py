"""A stand-in for the ``pymsalruntime`` module, for unit tests of the broker adapter.

It offers only the public names the adapter is expected to use. Touching any other attribute, such as
an interactive sign-in function, raises an error so the test fails.
"""


class _Status:
    Status_Ok = 0
    Status_InteractionRequired = 1
    Status_Error = 2


class _Error:
    def __init__(self, status, code):
        self._status = status
        self._code = code

    def get_status(self):
        return self._status

    def get_error_code(self):
        return self._code


class _Account:
    def __init__(self, user_name):
        self._user_name = user_name

    def get_user_name(self):
        return self._user_name


class _DiscoverResult:
    def __init__(self, accounts, error=None):
        self._accounts = accounts
        self._error = error

    def get_accounts(self):
        return self._accounts

    def get_error(self):
        return self._error


class _AuthResult:
    def __init__(self, error=None):
        self._error = error

    def get_error(self):
        return self._error


class _Handle:
    def __init__(self):
        self.cancelled = False

    def cancel_async_operation(self):
        self.cancelled = True


class Parameters:
    def __init__(self, client_id, authority):
        self.client_id = client_id
        self.authority = authority
        self.scopes = None
        self.redirect_uri = None
        self.claims = None
        self.token_to_renew = None

    def set_requested_scopes(self, scopes):
        self.scopes = scopes

    def set_redirect_uri(self, uri):
        self.redirect_uri = uri

    def set_decoded_claims(self, claims):
        self.claims = claims

    def set_access_token_to_renew(self, token):
        self.token_to_renew = token


class FakeModule:
    """Behaves like ``pymsalruntime``; ``behaviour`` decides what the broker answers."""

    Response_Status = _Status

    def __init__(self, user_names=('user@example.test',), auth_error=None, discover_error=None,
                 answer=True):
        self.accounts = [_Account(name) for name in user_names]
        self.auth_error = auth_error
        self.discover_error = discover_error
        self.answer = answer
        self.parameters = []
        self.acquired_for = []
        self.discovered_for = []
        self.handles = []

    def MSALRuntimeAuthParameters(self, client_id, authority):  # noqa: N802 - mirrors the library
        created = Parameters(client_id, authority)
        self.parameters.append(created)
        return created

    def discover_accounts(self, client_id, correlation_id, callback):
        self.discovered_for.append(client_id)
        handle = _Handle()
        self.handles.append(handle)
        if self.answer:
            callback(_DiscoverResult(self.accounts, self.discover_error))
        return handle

    def acquire_token_silently(self, parameters, correlation_id, account, callback):
        self.acquired_for.append(account)
        handle = _Handle()
        self.handles.append(handle)
        if self.answer:
            callback(_AuthResult(self.auth_error))
        return handle

    def error(self, status, code):
        return _Error(status, code)

    def __getattr__(self, name):
        raise AssertionError('the broker adapter used pymsalruntime.{}'.format(name))


def module(**options):
    return FakeModule(**options)



