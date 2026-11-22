.. :changelog:

Release History
===============

0.1.0
++++++
* Add ``az account refresh-token``, which gets a new access token for the signed-in account without signing in again. It takes the selection arguments of ``az account get-access-token``.
* Prove that the token is new: it must differ from the previous one and have been issued no earlier than 10 minutes before the command started.
* With the Windows or macOS broker, renew the token in the broker when the Azure CLI's own request does not return a new one. This path is not yet verified on real systems; it fails closed.
* Report ``refreshed``, or ``issued`` when the token the command started from was itself obtained during the same run (judged from the issue times of the old and new token), with fingerprints of the old and new token, never the tokens themselves.
* Add ``--show-claims`` to print the decoded payload of the new token.
* Require Azure CLI 2.71.0 or later.
