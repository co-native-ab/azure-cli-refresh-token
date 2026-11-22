"""Fixtures for the integration tests.

The tests run the real Azure CLI with the extension installed from the built wheel against the fake
identity provider in ``tests/fake_entra``. Every Azure CLI call gets its own temporary configuration
directory and home directory, so the tester's own Azure CLI sign-in is never read or written.

Environment variables:

* ``AZ_PYTHON``: interpreter of the virtual environment the Azure CLI is installed in. Without it
  the ``az`` found on ``PATH`` is used.
* ``EXTENSION_WHEEL``: a wheel to install. Without it the wheel is built from ``src/refresh-token``.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from collections import namedtuple

import pytest

from azext_refresh_token import proof
from fake_entra import FakeEntra, HOME_TENANT

REPOSITORY = pathlib.Path(__file__).resolve().parents[2]
CLOUD_NAME = 'fakeentra'
CALL_TIMEOUT_SECONDS = 60
REAL_HOME = pathlib.Path.home()
REAL_CONFIG_DIR = pathlib.Path(os.environ.get('AZURE_CONFIG_DIR') or REAL_HOME / '.azure')
# Only these files are compared, by name, size and modification time. They are never opened.
WATCHED_FILES = ('msal_token_cache.json', 'azureProfile.json', 'clouds.config', 'config')

Result = namedtuple('Result', ['returncode', 'stdout', 'stderr', 'seconds'])

recorded_envs = []


def snapshot_real_config():
    """Name, size and modification time of the watched files in the tester's own configuration
    directory, or None when it does not exist (for example on a CI machine)."""
    if not REAL_CONFIG_DIR.is_dir():
        return None
    snapshot = {}
    for name in WATCHED_FILES:
        try:
            info = (REAL_CONFIG_DIR / name).stat()
        except OSError:
            snapshot[name] = None
        else:
            snapshot[name] = (info.st_size, info.st_mtime_ns)
    return snapshot


_session_snapshot = {}


def pytest_sessionstart(session):
    _session_snapshot['before'] = snapshot_real_config()


def pytest_sessionfinish(session, exitstatus):
    before = _session_snapshot.get('before')
    if before is None:
        return
    after = snapshot_real_config()
    if after != before:
        print('\nThe default Azure CLI configuration directory changed during the test run: '
              '{} != {}'.format(before, after), file=sys.stderr)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _inside(path, parent):
    try:
        pathlib.Path(path).resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _scrubbed_environment():
    drop_exact = {'ACC_CLOUD', 'MSI_ENDPOINT', 'IDENTITY_ENDPOINT', 'IDENTITY_HEADER',
                  'COPILOT_AGENT_SESSION_ID'}
    environment = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if upper.startswith('AZURE_') or upper in drop_exact or upper.endswith('_PROXY'):
            continue
        environment[key] = value
    return environment


def make_environment(config_dir, home, extension_dir, ca_path):
    environment = _scrubbed_environment()
    environment.update({
        'AZURE_CONFIG_DIR': str(config_dir),
        'AZURE_EXTENSION_DIR': str(extension_dir),
        'HOME': str(home),
        'USERPROFILE': str(home),
        'AZURE_CORE_INSTANCE_DISCOVERY': 'false',
        'AZURE_CORE_COLLECT_TELEMETRY': 'false',
        'AZURE_CORE_ENABLE_BROKER_ON_WINDOWS': 'false',
        'AZURE_CORE_NO_COLOR': 'true',
        'PYTHONIOENCODING': 'utf-8',
    })
    if ca_path is not None:
        environment['REQUESTS_CA_BUNDLE'] = str(ca_path)
    for key in ('AZURE_CONFIG_DIR', 'HOME', 'USERPROFILE'):
        value = pathlib.Path(environment[key])
        assert value != REAL_HOME, 'refusing to use the real home directory'
        assert not _inside(value, REAL_HOME / '.azure'), 'refusing to use the real Azure directory'
    recorded_envs.append(dict(environment))
    return environment


def az_base_command():
    python = os.environ.get('AZ_PYTHON')
    if python:
        return [python, '-m', 'azure.cli']
    found = shutil.which('az')
    assert found, 'Azure CLI not found: put az on PATH or set AZ_PYTHON'
    if sys.platform == 'win32' and found.lower().endswith(('.cmd', '.bat')):
        return ['cmd', '/c', found]
    return [found]


def run_az(base, args, environment, cwd, timeout=CALL_TIMEOUT_SECONDS):
    started = time.monotonic()
    completed = subprocess.run(
        list(base) + list(args), env=environment, cwd=str(cwd), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
    return Result(completed.returncode, completed.stdout.decode('utf-8', 'replace'),
                  completed.stderr.decode('utf-8', 'replace'), time.monotonic() - started)


@pytest.fixture(scope='session')
def wheel(tmp_path_factory):
    given = os.environ.get('EXTENSION_WHEEL')
    if given:
        return pathlib.Path(given)
    output = tmp_path_factory.mktemp('wheel')
    subprocess.run(
        [sys.executable, '-m', 'build', '--wheel', '--no-isolation', '--outdir', str(output),
         str(REPOSITORY / 'src' / 'refresh-token')],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return next(output.glob('*.whl'))


@pytest.fixture(scope='session')
def az_command():
    return az_base_command()


@pytest.fixture(scope='session')
def extension_dir(tmp_path_factory, wheel, az_command):
    """The extension installed once from the wheel, before any custom certificate bundle is set."""
    root = tmp_path_factory.mktemp('extension-install')
    directory = root / 'extensions'
    environment = make_environment(root / 'config', root / 'home', directory, None)
    (root / 'home').mkdir()
    result = run_az(az_command, ['extension', 'add', '--source', str(wheel), '--yes'],
                    environment, root, timeout=300)
    assert result.returncode == 0, result.stderr
    version = run_az(az_command, ['version', '-o', 'json'], environment, root)
    print('\nazure-cli:', json.loads(version.stdout).get('azure-cli'))
    return directory


@pytest.fixture
def fake(tmp_path):
    server = FakeEntra(tmp_path)
    server.start()
    yield server
    server.stop()


class Az:
    """Runs the Azure CLI with isolated configuration against the fake identity provider."""

    def __init__(self, base, environment, cwd, fake):
        self.base = base
        self.environment = environment
        self.cwd = cwd
        self.fake = fake

    def run(self, *args, timeout=CALL_TIMEOUT_SECONDS):
        return run_az(self.base, args, self.environment, self.cwd, timeout)

    def ok(self, *args):
        result = self.run(*args)
        assert result.returncode == 0, 'az {} failed: {}'.format(' '.join(args), result.stderr)
        return result

    def json(self, *args):
        return json.loads(self.ok(*args, '-o', 'json').stdout)

    def register_cloud(self):
        config = self.cwd / 'cloud.json'
        config.write_text(json.dumps(self.fake.cloud_config()), encoding='utf-8')
        self.ok('cloud', 'register', '--name', CLOUD_NAME, '--cloud-config', '@' + str(config))
        self.ok('cloud', 'set', '--name', CLOUD_NAME)

    def login_user(self, tenant=HOME_TENANT):
        self.register_cloud()
        self.ok('login', '--use-device-code', '--tenant', tenant)

    def login_service_principal(self, tenant=HOME_TENANT):
        self.register_cloud()
        state = self.fake.state
        self.ok('login', '--service-principal', '--username', state.app_id,
                '--password', state.app_secret, '--tenant', tenant)

    def token(self, *args):
        """The token ``az account get-access-token`` returns, as a dictionary."""
        return self.json('account', 'get-access-token', *args)

    def refresh(self, *args):
        """Run ``az account refresh-token`` and return the result and its parsed output (or None)."""
        result = self.run('account', 'refresh-token', *args, '-o', 'json')
        parsed = None
        if result.returncode == 0 and result.stdout.strip():
            parsed = json.loads(result.stdout)
        return result, parsed

    def fingerprint(self, *args):
        return proof.fingerprint(self.token(*args)['accessToken'])


@pytest.fixture
def az(tmp_path, fake, az_command, extension_dir):
    config = tmp_path / 'azure-config'
    home = tmp_path / 'home'
    cwd = tmp_path / 'cwd'
    for directory in (config, home, cwd):
        directory.mkdir()
    environment = make_environment(config, home, extension_dir, fake.ca_path)
    yield Az(az_command, environment, cwd, fake)
    assert not (home / '.azure').exists(), 'the Azure CLI wrote to the home directory'


def token_parts(token):
    return token.split('.') if token.count('.') == 2 else [token]


def assert_no_token_leak(fake, *texts):
    """Assert that none of the tokens the fake issued, nor any segment of them, appears in texts."""
    needles = set()
    for text in fake.state.all_issued_texts():
        needles.add(text)
        needles.update(token_parts(text))
    for text in texts:
        for needle in needles:
            assert needle not in text, 'a token or a part of one leaked into the output'


def payload_of(token):
    """The decoded payload of a token the fake issued."""
    return proof.inspect(token).claims

