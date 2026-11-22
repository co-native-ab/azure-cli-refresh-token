.. :changelog:

Release History
===============

0.1.0
++++++
* Add ``az account refresh-token``, which gets a new access token for the signed-in account without signing in again. It takes the selection arguments of ``az account get-access-token``.
* Prove that the token is new: it must differ from the previous one and have been issued no earlier than 10 minutes before the command started.
* Report ``refreshed`` or ``issued`` with fingerprints of the old and new token, never the tokens themselves.
* Add ``--show-claims`` to print the decoded payload of the new token.
* Require Azure CLI 2.71.0 or later.
