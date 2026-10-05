"""A disposable PostgreSQL cluster that never reads the application database URL."""
import atexit
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
        candidates = Path("/usr/lib/postgresql").glob("*/bin")
        self.binary = next(
            (directory for directory in sorted(
                candidates, key=lambda directory: int(directory.parent.name), reverse=True
            ) if (directory / "initdb").exists() and (directory / "pg_ctl").exists()),
            None,
        )
        if self.binary is None:
            raise RuntimeError("PostgreSQL initdb/pg_ctl are required for the isolated test suite")

    def start(self):
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
                        f"PostGIS server extension for PostgreSQL {self.binary.parent.name} "
                        "is required for the isolated test suite"
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
