"""Start the production image with no external network and a disposable PostGIS DB."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.postgres_cluster import TemporaryPostgres
from migrations.initialize import initialize_database

PROBE = """
import json
import urllib.error
import urllib.request
base = 'http://127.0.0.1:8000'
def get(path):
    with urllib.request.urlopen(base + path, timeout=3) as response:
        assert response.status == 200
        return json.load(response)
assert get('/health') == {'ok': True}
assert isinstance(get('/api/v1/sports'), list)
assert get('/') == {'message': 'Hello World!'}
assert '/api/v1/rooms' in get('/openapi.json')['paths']
try:
    get('/api/v1/users/me')
except urllib.error.HTTPError as error:
    assert error.code == 401
else:
    raise AssertionError('Protected endpoint permitted a guest')
print('Container health, SQL query, OpenAPI and authorization checks passed.')
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    name = "modeer-ci-" + uuid.uuid4().hex[:12]
    cluster = TemporaryPostgres().start()
    try:
        url = cluster.create_database()
        initialize_database(url)
        parsed = urlsplit(url)
        # Bind-mount only the owned cluster's Unix socket; the container cannot reach the internet.
        container_url = (f"postgresql+psycopg2://{parsed.username}@{parsed.path}"
                         f"?host=/run/modeer-pg-socket&port={parsed.port}")
        subprocess.run([
            "docker", "run", "--detach", "--name", name, "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--mount", f"type=bind,source={cluster.directory / 'socket'},target=/run/modeer-pg-socket,readonly",
            "--env", f"DATABASE_URL={container_url}",
            "--env", "JWT_SECRET=modeer-container-isolated-test-secret-2026",
            "--env", "CORS_ORIGINS=http://127.0.0.1:5174",
            "--env", "LIFECYCLE_WORKER=off", "--env", "GOOGLE_CLIENT_ID=isolated-client",
            "--env", "PORT=8000", args.image,
        ], check=True, capture_output=True, text=True)
        deadline = time.monotonic() + 60
        last_probe = None
        while time.monotonic() < deadline:
            last_probe = subprocess.run(["docker", "exec", name, "python", "-c", PROBE],
                                        capture_output=True, text=True, timeout=15)
            if last_probe.returncode == 0:
                print(last_probe.stdout.strip())
                print(json.dumps({"image": args.image, "network": "none", "database": "disposable PostGIS"}))
                return 0
            state = subprocess.run(["docker", "inspect", "--format={{.State.Running}}", name],
                                   capture_output=True, text=True, check=True)
            if state.stdout.strip() != "true":
                break
            time.sleep(.2)
        subprocess.run(["docker", "logs", name], check=False)
        raise RuntimeError("Production container failed startup checks: " + (last_probe.stderr if last_probe else "no probe"))
    finally:
        # Docker can create a stopped container before `run` fails. Clean up the
        # unique owned name even in that case, and always stop the database.
        try:
            subprocess.run(["docker", "rm", "--force", name], check=False, capture_output=True)
        except OSError:
            pass
        finally:
            cluster.stop()


if __name__ == "__main__":
    raise SystemExit(main())
