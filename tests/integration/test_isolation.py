"""The tester's own Azure CLI configuration is never used."""

import pathlib

import pytest

from conftest import REAL_CONFIG_DIR, REAL_HOME, recorded_envs, snapshot_real_config

pytestmark = pytest.mark.integration


def test_default_azure_config_dir_is_never_used(az, fake, tmp_path):
    before = snapshot_real_config()
    az.login_user()
    az.token()
    az.run('account', 'refresh-token')
    assert snapshot_real_config() == before

    assert recorded_envs
    root = pathlib.Path(tmp_path).parent.resolve()
    for environment in recorded_envs:
        for key in ('AZURE_CONFIG_DIR', 'HOME', 'USERPROFILE'):
            value = pathlib.Path(environment[key]).resolve()
            assert root in value.parents or value == root
            assert value != REAL_HOME
            assert value != REAL_CONFIG_DIR
    assert not (pathlib.Path(az.environment['HOME']) / '.azure').exists()
