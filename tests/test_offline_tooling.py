"""The offline tools must reject external destinations and unsafe prerequisites."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.offline_network import is_loopback_host
from tests.postgres_cluster import TemporaryPostgres


@pytest.mark.parametrize('host,allowed', [
    ('127.0.0.1', True), ('127.20.30.40', True), ('::1', True), ('::ffff:127.0.0.1', True),
    ('localhost', True), ('LOCALHOST.', True), (b'127.0.0.1', True),
    ('0.0.0.0', False), ('192.168.1.1', False), ('8.8.8.8', False), ('example.com', False),
    ('localhost.attacker.test', False), ('127.0.0.1.attacker.test', False),
])
def test_network_allowlist_is_loopback_only(host, allowed):
    assert is_loopback_host(host) is allowed


def test_outbound_dns_tcp_and_udp_are_blocked_before_any_network_access():
    code = '''
import json, socket, psycopg2
from tests.offline_network import install, blocked_attempts, OfflineNetworkError
install()
attempts=[lambda: socket.getaddrinfo('example.com',443),
          lambda: socket.socket().connect(('8.8.8.8',443)),
          lambda: socket.socket(type=socket.SOCK_DGRAM).sendto(b'test',('8.8.8.8',53)),
          lambda: psycopg2.connect('host=external.example dbname=production'),
          lambda: psycopg2.connect(service='production')]
for attempt in attempts:
    try: attempt()
    except OfflineNetworkError: pass
    else: raise AssertionError('External operation was not blocked')
print(json.dumps(blocked_attempts()))
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ['example.com', '8.8.8.8', '8.8.8.8', 'external.example', 'postgresql-service-indirection']


def test_explicit_postgres_selection_rejects_missing_binaries(monkeypatch, tmp_path):
    monkeypatch.setenv('MODEER_TEST_PG_BIN', str(tmp_path))
    with pytest.raises(RuntimeError, match='MODEER_TEST_PG_BIN'):
        TemporaryPostgres()


def test_cluster_refuses_unowned_database_creation_and_deletion(pg_cluster):
    with pytest.raises(ValueError, match='generated'):
        pg_cluster.create_database('production')
    with pytest.raises(ValueError, match='outside'):
        pg_cluster.drop_database('postgresql+psycopg2://owner@untrusted.example/live')
    with pytest.raises(ValueError, match='unowned'):
        pg_cluster.drop_database(pg_cluster.url)


def test_runner_preflight_fails_closed_without_installing_missing_postgres(tmp_path):
    environment = {**os.environ, 'MODEER_TEST_PG_BIN': str(tmp_path), 'PIPENV_DONT_LOAD_ENV': '1'}
    result = subprocess.run([sys.executable, '-m', 'tests.run_offline', '--check'],
                            cwd=Path(__file__).resolve().parents[1], env=environment,
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 1 and 'Offline test preflight failed' in result.stderr
    assert 'MODEER_TEST_PG_BIN' in result.stderr


def test_guard_disables_dotenv_discovery_before_importing_the_real_application():
    code = '''
import os
import dotenv, dotenv.main
os.environ.pop('PYTHON_DOTENV_DISABLED', None)
def forbidden_discovery(*args, **kwargs):
    raise AssertionError('Application tried to discover a production .env file')
dotenv.find_dotenv = dotenv.main.find_dotenv = forbidden_discovery
from tests.offline_network import install
install()
os.environ.update(DATABASE_URL='postgresql+psycopg2://isolated@127.0.0.1:1/unused',
                  JWT_SECRET='offline-dotenv-import-check-secret-long-enough', LIFECYCLE_WORKER='off')
import main
assert os.environ['PYTHON_DOTENV_DISABLED'] == '1'
print('Application imported without dotenv discovery')
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'Application imported without dotenv discovery'


@pytest.mark.parametrize('problem', ['missing-manifest', 'invalid-json', 'empty', 'duplicate', 'outside-path', 'missing-suite', 'unregistered-suite'])
def test_required_suite_manifest_rejects_missing_or_invalid_test_inventories(tmp_path, problem):
    from tests.run_offline import load_required_suites
    suite = tmp_path / 'test_critical.py'
    suite.write_text('def test_critical(): pass\n')
    manifest = tmp_path / 'required_suites.json'
    data = {'schema_version': 1, 'required_suites': ['test_critical.py']}
    if problem == 'empty': data['required_suites'] = []
    if problem == 'duplicate': data['required_suites'] *= 2
    if problem == 'outside-path': data['required_suites'] = ['../test_critical.py']
    if problem == 'missing-suite': suite.unlink()
    if problem == 'unregistered-suite': (tmp_path / 'test_unregistered.py').write_text('def test_new(): pass\n')
    if problem != 'missing-manifest':
        manifest.write_text('not-json' if problem == 'invalid-json' else json.dumps(data))
    with pytest.raises((RuntimeError, ValueError)):
        load_required_suites(manifest, tmp_path)


def test_required_suite_gate_rejects_uncollected_modules_and_skipped_required_tests():
    from types import SimpleNamespace
    from tests.run_offline import RequiredTests
    required = RequiredTests(['test_first.py', 'test_missing.py'])
    required.pytest_collection_finish(SimpleNamespace(items=[SimpleNamespace(path=Path('test_first.py'))]))
    required.pytest_runtest_logreport(SimpleNamespace(skipped=True, nodeid='test_first.py::test_required', when='setup'))
    assert required.collected == 1
    assert required.invalid == ['No tests collected from test_missing.py',
                                'Required test skipped or xfailed: test_first.py::test_required']
