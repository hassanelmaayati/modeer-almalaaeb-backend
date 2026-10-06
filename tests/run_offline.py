"""Run every backend test offline, with reports and a fail-closed result.

Usage: PIPENV_DONT_LOAD_ENV=1 pipenv run python -m tests.run_offline
Prerequisites must already be installed; this entrypoint never downloads them.
"""
import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from importlib import metadata, util
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'tests' / 'artifacts'


class Tee:
    def __init__(self, stream, log):
        self.stream, self.log = stream, log
        self.lock = threading.RLock()

    def write(self, value):
        with self.lock:
            self.log.write(value)
            return self.stream.write(value)

    def flush(self):
        with self.lock:
            self.log.flush()
            self.stream.flush()

    def isatty(self):
        return False


class RequiredTests:
    def __init__(self, required_suites):
        self.required_suites = set(required_suites)
        self.collected = 0
        self.outcomes = Counter()
        self.invalid = []

    def pytest_collection_finish(self, session):
        self.collected = len(session.items)
        collected = {Path(item.path).name for item in session.items}
        for missing in sorted(self.required_suites - collected):
            self.invalid.append(f'No tests collected from {missing}')

    def pytest_runtest_logreport(self, report):
        if report.skipped or getattr(report, 'wasxfail', None):
            self.invalid.append(f'Required test skipped or xfailed: {report.nodeid}')
        if report.when == 'call':
            self.outcomes[report.outcome] += 1


def load_required_suites(manifest_path=None, suites_directory=None):
    directory = Path(suites_directory) if suites_directory else ROOT / 'tests'
    manifest = Path(manifest_path) if manifest_path else directory / 'required_suites.json'
    if not manifest.is_file():
        raise RuntimeError('Required suites manifest is missing: ' + str(manifest))
    data = json.loads(manifest.read_text())
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data.get('schema_version') != 1:
        raise RuntimeError('Required suites manifest must have schema_version 1')
    suites = data.get('required_suites')
    if not isinstance(suites, list) or not suites:
        raise RuntimeError('Required suites manifest must contain a nonempty required_suites list')
    if any(not isinstance(name, str) or Path(name).name != name or not name.startswith('test_') or not name.endswith('.py') for name in suites):
        raise RuntimeError('Required suites manifest contains an invalid module filename')
    if len(suites) != len(set(suites)):
        raise RuntimeError('Required suites manifest contains duplicate modules')
    missing = sorted(name for name in suites if not (directory / name).is_file())
    if missing:
        raise RuntimeError('Required test suite files are missing: ' + ', '.join(missing))
    unregistered = sorted(path.name for path in directory.glob('test_*.py') if path.name not in suites)
    if unregistered:
        raise RuntimeError('Register new test suites in required_suites.json: ' + ', '.join(unregistered))
    return suites


def preflight():
    if sys.version_info[:2] != (3, 14):
        raise RuntimeError('Python 3.14 is required by Pipfile; select the project virtualenv')
    packages = {'pytest': 'pytest', 'pytest_cov': 'pytest-cov', 'pytest_timeout': 'pytest-timeout',
                'sqlalchemy': 'SQLAlchemy', 'psycopg2': 'psycopg2-binary'}
    missing = [package for module, package in packages.items() if util.find_spec(module) is None]
    if missing:
        raise RuntimeError('Missing installed development dependencies: ' + ', '.join(missing) +
                           '. During setup, run PIPENV_DONT_LOAD_ENV=1 pipenv sync --dev; then retry offline.')
    from tests.offline_network import install
    from tests.postgres_cluster import TemporaryPostgres
    install()
    cluster = TemporaryPostgres()
    try:
        cluster.start()  # Also verifies matching PostGIS is available.
    finally:
        cluster.stop()
    return {'python': sys.version.split()[0], 'postgres_bin': str(cluster.binary),
            'packages': {package: metadata.version(package) for package in packages.values()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify installed prerequisites without running tests')
    options = parser.parse_args()
    # Ignore local environment settings and pytest plugins/options from the shell.
    os.environ['PIPENV_DONT_LOAD_ENV'] = '1'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ.pop('PYTEST_ADDOPTS', None)
    os.environ.pop('PYTEST_PLUGINS', None)
    sys.dont_write_bytecode = True
    os.chdir(ROOT)
    try:
        suites = load_required_suites()
        environment = preflight()
    except Exception as error:
        print(f'Offline test preflight failed: {error}', file=sys.stderr)
        return 1
    print('Offline prerequisites verified: ' + json.dumps(environment))
    if options.check:
        return 0
    import pytest
    from tests.offline_network import blocked_attempts
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    os.environ['COVERAGE_FILE'] = str(ARTIFACTS / '.coverage')
    required = RequiredTests(suites)
    with (ARTIFACTS / 'pytest.log').open('w') as log:
        with redirect_stdout(Tee(sys.stdout, log)), redirect_stderr(Tee(sys.stderr, log)):
            result = pytest.main([
                str(ROOT / 'tests'), '-q', '--tb=short', '-p', 'no:cacheprovider',
                '--strict-markers', '--strict-config', '--timeout=45',
                '--junitxml=' + str(ARTIFACTS / 'junit.xml'),
                '--cov=config', '--cov=controllers', '--cov=dependencies', '--cov=models',
                '--cov=serializers', '--cov=services', '--cov=migrations', '--cov=scripts', '--cov=main', '--cov=database',
                '--cov-branch', '--cov-report=term-missing:skip-covered',
                '--cov-report=xml:' + str(ARTIFACTS / 'coverage.xml'),
                '--cov-report=json:' + str(ARTIFACTS / 'coverage.json'),
            ], plugins=[required])
    if not required.collected or not required.outcomes['passed']:
        required.invalid.append('The complete required test suite did not execute')
    attempts = blocked_attempts()
    if attempts:
        required.invalid.append('Unexpected outbound connections were attempted: ' + repr(attempts))
    if required.invalid:
        for reason in required.invalid:
            print('Offline gate failed: ' + reason, file=sys.stderr)
        result = result or 1
    report = {**environment, 'required_suites': suites, 'collected': required.collected, 'outcomes': dict(required.outcomes),
              'blocked_network_attempts': attempts, 'gate_errors': required.invalid, 'exit_code': int(result)}
    (ARTIFACTS / 'offline-summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Offline test reports: ' + str(ARTIFACTS))
    return int(result)


if __name__ == '__main__':
    raise SystemExit(main())
