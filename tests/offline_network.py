"""Deny outbound Python networking while keeping disposable local services usable.

Install before application imports, including in the frontend's isolated API
bootstrap. PostgreSQL connections are additionally isolated through explicitly
generated loopback database URLs; never load the application's .env in tests.
"""
import ipaddress
import os
import socket
import threading

_installed = False
_blocked = []
_lock = threading.Lock()


class OfflineNetworkError(RuntimeError):
    pass


def is_loopback_host(host):
    if isinstance(host, bytes):
        host = host.decode('ascii', errors='replace')
    if host is None or str(host).lower().rstrip('.') == 'localhost':
        return True
    try:
        address = ipaddress.ip_address(str(host).split('%', 1)[0])
        return address.is_loopback or bool(getattr(address, 'ipv4_mapped', None) and address.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def blocked_attempts():
    with _lock:
        return list(_blocked)


def _require_local(host):
    if not is_loopback_host(host):
        with _lock:
            _blocked.append(str(host))
        raise OfflineNetworkError(f'Offline tests refused a non-loopback destination: {host}')


def install():
    global _installed
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    if _installed:
        return
    _installed = True
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        os.environ.pop(name, None)
    os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'
    # libpq bypasses Python's socket methods. Strip implicit connection defaults
    # and inspect its explicit DSN before it can resolve/connect to a host.
    for name in ('PGSERVICE', 'PGSERVICEFILE', 'PGHOST', 'PGHOSTADDR', 'PGDATABASE', 'PGUSER', 'PGPASSWORD', 'PGPASSFILE'):
        os.environ.pop(name, None)
    import psycopg2
    from psycopg2.extensions import parse_dsn
    original_postgres_connect = psycopg2.connect

    def postgres_connect(dsn=None, *args, **kwargs):
        parameters = parse_dsn(dsn) if dsn else {}
        parameters.update({name: value for name, value in kwargs.items() if name in ('host', 'hostaddr', 'service')})
        if parameters.get('service'):
            _require_local('postgresql-service-indirection')
        for name in ('host', 'hostaddr'):
            for host in str(parameters.get(name) or '').split(','):
                # An omitted host or an absolute Unix socket path stays local.
                if host and not (name == 'host' and os.path.isabs(host)):
                    _require_local(host)
        return original_postgres_connect(dsn, *args, **kwargs)

    psycopg2.connect = postgres_connect
    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex
    original_sendto = socket.socket.sendto
    original_getaddrinfo = socket.getaddrinfo
    original_gethostbyname, original_gethostbyname_ex = socket.gethostbyname, socket.gethostbyname_ex

    def check_socket(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            _require_local(address[0])

    def connect(sock, address):
        check_socket(sock, address)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        check_socket(sock, address)
        return original_connect_ex(sock, address)

    def sendto(sock, data, *args):
        check_socket(sock, args[-1])
        return original_sendto(sock, data, *args)

    def getaddrinfo(host, *args, **kwargs):
        _require_local(host)
        return original_getaddrinfo(host, *args, **kwargs)

    def gethostbyname(host):
        _require_local(host)
        return original_gethostbyname(host)

    def gethostbyname_ex(host):
        _require_local(host)
        return original_gethostbyname_ex(host)

    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
    socket.socket.sendto = sendto
    socket.getaddrinfo = getaddrinfo
    socket.gethostbyname, socket.gethostbyname_ex = gethostbyname, gethostbyname_ex
