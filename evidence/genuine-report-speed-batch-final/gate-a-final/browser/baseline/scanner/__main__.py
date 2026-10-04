"""Loopback-only source distribution launcher and safe offline restore command."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import stat
import sys
import threading
import time
import webbrowser

HOST = "127.0.0.1"
VERSION = "0.3.11"


class InstanceAlreadyRunning(RuntimeError):
    """The data directory is already owned by a running scanner."""


@contextmanager
def data_directory_lock(data_dir: str | Path):
    """Hold an OS-owned lock, automatically released even after process exit."""
    directory = Path(data_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = directory / ".runtime.lock"
    if lock_path.is_symlink():
        raise OSError("the runtime lockfile must not be a symbolic link")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    stream = os.fdopen(descriptor, "r+b", buffering=0)
    acquired = False
    try:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise OSError("the runtime lockfile must be a regular file")
        if sys.platform == "win32":
            import msvcrt
            # Windows byte-range locks require a byte to exist at offset zero.
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"\0")
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise InstanceAlreadyRunning(f"another scanner process is using {directory}; stop it or choose a different --data-dir") from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                raise InstanceAlreadyRunning(f"another scanner process is using {directory}; stop it or choose a different --data-dir") from exc
        acquired = True
        stream.seek(0)
        stream.write(f"{os.getpid()}\n".encode("ascii"))
        stream.truncate()
        yield directory
    finally:
        try:
            if acquired:
                stream.seek(0)
                if sys.platform == "win32":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "solana-wallet-scanner"


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _announce(server: object, url: str, browser: bool) -> None:
    # Only open the browser after Uvicorn has completed app startup.
    while not getattr(server, "started", False):
        if getattr(server, "should_exit", False):
            return
        time.sleep(0.1)
    print(f"\nSolana Wallet Scanner is ready: {url}\nPress Ctrl+C to stop.\n", flush=True)
    if browser:
        try:
            if not webbrowser.open(url, new=2):
                print("Automatic browser opening was unavailable. Open the URL above.", flush=True)
        except Exception:
            print("Automatic browser opening was unavailable. Open the URL above.", flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "restore":
        from .restore import main as restore_main
        return restore_main(argv[1:])
    parser = argparse.ArgumentParser(description="Run the read-only scanner on 127.0.0.1 only.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir(), help="local storage directory")
    parser.add_argument("--port", type=_port, default=8765, help="loopback port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="print the session URL without opening a browser")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or later is required")
    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "index.html"
    if not dist.is_file():
        parser.error("the interface has not been built; run setup.sh (Windows: setup.ps1), or run npm ci and npm run build in frontend")
    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Keeping this socket through startup prevents a port-check race.
        listen_socket.bind((HOST, args.port))
        listen_socket.listen(2048)
    except OSError as exc:
        listen_socket.close()
        parser.error(f"cannot listen on {HOST}:{args.port}: {exc}; choose a free port with --port")
    try:
        import uvicorn
        from .app import create_app
        with data_directory_lock(args.data_dir) as directory:
            token = secrets.token_urlsafe(32)
            app = create_app(directory, token)
            config = uvicorn.Config(app, host=HOST, port=args.port, reload=False, workers=1,
                                    proxy_headers=False, server_header=False, log_level="info")
            server = uvicorn.Server(config)
            url = f"http://{HOST}:{args.port}/#session={token}"
            threading.Thread(target=_announce, args=(server, url, not args.no_browser), daemon=True).start()
            server.run(sockets=[listen_socket])
            return 0 if server.started else 1
    except ImportError as exc:
        parser.error(f"a Python dependency is missing: {exc}; run setup.sh --skip-frontend (Windows: setup.ps1 -SkipFrontend)")
    except InstanceAlreadyRunning as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        return 0
    except (OSError, sqlite3.Error) as exc:
        parser.error(f"cannot start the local scanner: {exc}; check the data directory and local permissions")
    finally:
        listen_socket.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
