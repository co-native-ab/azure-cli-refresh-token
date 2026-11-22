"""Static checks that keep the extension on the Azure CLI's published surface."""

import ast
import pathlib
import sys

PACKAGE = pathlib.Path(__file__).resolve().parents[2] / 'src' / 'refresh-token' / 'azext_refresh_token'
SOURCES = sorted(PACKAGE.glob('*.py'))
PURE_MODULES = ('selection.py', 'proof.py', 'result.py')
OWNED_ROOTS = ('azure', 'msal', 'knack', 'pymsalruntime')
ALLOWED_PRIVATE_MODULE = 'azure.cli.core._profile'
FORBIDDEN_WORDS = (
    'acquire_token_interactively', 'signin_interactively', 'webbrowser', 'initiate_device_flow',
    'acquire_token_by_device_flow', 'use_device_code',
)
TOKEN_NAMES = ('token', 'access_token', 'raw')


def parse(path):
    return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def imports(tree):
    """Yield (module, imported names) for every import statement."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, [alias.name]
        elif isinstance(node, ast.ImportFrom):
            yield node.module or '', [alias.name for alias in node.names]


def test_package_has_sources():
    assert PACKAGE.joinpath('custom.py').exists()


def test_no_underscore_name_is_imported_from_other_projects():
    for path in SOURCES:
        for module, names in imports(parse(path)):
            if module.split('.')[0] not in OWNED_ROOTS:
                continue
            if module == ALLOWED_PRIVATE_MODULE:
                assert names == ['Profile'], path.name
                continue
            for part in module.split('.'):
                assert not part.startswith('_'), (path.name, module)
            for name in names:
                assert not name.startswith('_'), (path.name, module, name)


def test_pure_modules_import_only_the_standard_library():
    standard = set(sys.stdlib_module_names)
    for name in PURE_MODULES:
        for module, _ in imports(parse(PACKAGE / name)):
            root = module.split('.')[0]
            assert root in standard or root == 'azext_refresh_token', (name, module)


def test_no_interactive_sign_in_is_referenced():
    for path in SOURCES:
        text = path.read_text(encoding='utf-8')
        for word in FORBIDDEN_WORDS:
            assert word not in text, (path.name, word)


def test_nothing_is_patched_at_runtime():
    for path in SOURCES:
        tree = parse(path)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update((alias.asname or alias.name).split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update(alias.asname or alias.name for alias in node.names)
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                    assert target.value.id not in imported, (path.name, node.lineno)


def mentions_token(node):
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in TOKEN_NAMES:
            return True
    return False


def test_nothing_prints_or_logs_a_token():
    log_methods = {'debug', 'info', 'warning', 'error', 'exception', 'critical', 'log'}
    for path in SOURCES:
        for node in ast.walk(parse(path)):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            is_print = isinstance(function, ast.Name) and function.id == 'print'
            is_log = isinstance(function, ast.Attribute) and function.attr in log_methods
            if is_print:
                raise AssertionError('print in {}:{}'.format(path.name, node.lineno))
            if is_log:
                for argument in list(node.args) + [keyword.value for keyword in node.keywords]:
                    assert not mentions_token(argument), (path.name, node.lineno)
