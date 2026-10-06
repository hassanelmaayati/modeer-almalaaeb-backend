"""A disposable PostgreSQL cluster that never reads the application database URL."""
import atexit
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import uuid

from sqlalchemy import create_engine, text


class TemporaryPostgres:
    def __init__(self):
        self.directory = None
        self.engine = None
        self.url = None
        self.binary = self.find_binaries()
        if self.binary is None:
            raise RuntimeError(
                "PostgreSQL initdb/pg_ctl are required. Install PostgreSQL and matching PostGIS, "
                "or set MODEER_TEST_PG_BIN to their bin directory."
            )

    @staticmethod
    def find_binaries():
        def valid(directory):
            return (directory / 'initdb').is_file() and (directory / 'pg_ctl').is_file()

        explicit = os.environ.get('MODEER_TEST_PG_BIN')
        if explicit:
            directory = Path(explicit).expanduser().resolve()
            if not valid(directory):
                raise RuntimeError('MODEER_TEST_PG_BIN must contain both initdb and pg_ctl')
            return directory
        candidates = []
        pg_config = shutil.which('pg_config')
        if pg_config:
            try:
                result = subprocess.run([pg_config, '--bindir'], capture_output=True, text=True,
                                        check=True, timeout=5)
                candidates.append(Path(result.stdout.strip()))
            except (OSError, subprocess.SubprocessError):
                pass
        initdb = shutil.which('initdb')
        if initdb:
            candidates.append(Path(initdb).resolve().parent)
        candidates.extend(sorted(Path('/usr/lib/postgresql').glob('*/bin'),
                                 key=lambda p: int(p.parent.name) if p.parent.name.isdigit() else 0,
                                 reverse=True))
        for root in ('/opt/homebrew/opt', '/usr/local/opt'):
            candidates.extend(sorted(Path(root).glob('postgresql*/bin'), reverse=True))
        return next((directory for directory in candidates if valid(directory)), None)

    def start(self):
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            raise RuntimeError('Run isolated PostgreSQL tests as a non-root user; initdb refuses root')
        self.directory = Path(tempfile.mkdtemp(prefix="modeer-pg-"))
        data = self.directory / "data"
        sockets = self.directory / "socket"
        sockets.mkdir()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        try:
            subprocess.run(
                [str(self.binary / "initdb"), "-D", str(data), "-U", "modeer_test",
                 "-A", "trust", "--no-locale", "--encoding=UTF8"],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                [str(self.binary / "pg_ctl"), "-D", str(data),
                 "-l", str(self.directory / "server.log"),
                 "-o", f"-F -k {sockets} -p {port} -h 127.0.0.1", "-w", "-t", "30", "start"],
                check=True, capture_output=True, text=True,
            )
            self.url = f"postgresql+psycopg2://modeer_test@127.0.0.1:{port}/postgres"
            self.engine = create_engine(self.url, isolation_level="AUTOCOMMIT")
            with self.engine.connect() as connection:
                available = connection.execute(text(
                    "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'postgis')"
                )).scalar_one()
                if not available:
                    raise RuntimeError(
                        f"PostGIS server extension for binaries at {self.binary} is required. "
                        "Install matching PostGIS or select another version with MODEER_TEST_PG_BIN."
                    )
            atexit.register(self.stop)
            return self
        except Exception:
            self.stop()
            raise

    def create_database(self, name=None):
        name = name or f"modeer_case_{uuid.uuid4().hex}"
        if not name.startswith("modeer_case_") or not name.replace("_", "").isalnum():
            raise ValueError("Only generated test database names are allowed")
        with self.engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        return self.url.rsplit("/", 1)[0] + "/" + name

    def drop_database(self, database_url):
        if database_url.rsplit("/", 1)[0] != self.url.rsplit("/", 1)[0]:
            raise ValueError("Refusing to touch a database outside this temporary cluster")
        name = database_url.rsplit("/", 1)[1]
        if not name.startswith("modeer_case_") or not name.replace("_", "").isalnum():
            raise ValueError("Refusing to drop an unowned database")
        with self.engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))

    def stop(self):
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None
        if self.directory is not None:
            subprocess.run(
                [str(self.binary / "pg_ctl"), "-D", str(self.directory / "data"),
                 "-m", "immediate", "-w", "stop"],
                capture_output=True,
            )
            shutil.rmtree(self.directory, ignore_errors=True)
            self.directory = None
