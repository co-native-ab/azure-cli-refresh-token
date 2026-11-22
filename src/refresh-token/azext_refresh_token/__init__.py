# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------


def __getattr__(name):
    # The Azure CLI looks up COMMAND_LOADER_CLS on this package. Importing the loader lazily keeps
    # the pure modules (selection, proof, result) importable where the Azure CLI is not installed,
    # which is how the unit tests run.
    if name == 'COMMAND_LOADER_CLS':
        from azext_refresh_token.loader import RefreshTokenCommandsLoader
        return RefreshTokenCommandsLoader
    raise AttributeError('module {!r} has no attribute {!r}'.format(__name__, name))
