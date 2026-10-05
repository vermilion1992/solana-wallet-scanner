"""Loopback-only positive check of websockets 16 automatic HTTP proxy/TLS."""
import asyncio
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from scanner.observer import connect as application_connect

connector = application_connect if "--application" in sys.argv else connect

original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex
socket_attempts = []


def local_connect(self, address):
    if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1"):
        raise AssertionError("Probe forbids non-loopback socket connections")
    socket_attempts.append("loopback")
    return original_connect(self, address)


def local_connect_ex(self, address):
    if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1"):
        raise AssertionError("Probe forbids non-loopback socket connections")
    socket_attempts.append("loopback")
    return original_connect_ex(self, address)


socket.socket.connect = local_connect
socket.socket.connect_ex = local_connect_ex


async def scenario(directory):
    certificate, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(certificate), "-days", "1",
        "-subj", "/CN=observer-probe.invalid", "-addext",
        "subjectAltName=DNS:observer-probe.invalid",
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    server_ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ssl.load_cert_chain(certificate, key)
    client_ssl = ssl.create_default_context(cafile=str(certificate))
    observations, pumps = [], []

    async def target(websocket):
        observations.append({"subscription": json.loads(await websocket.recv())["method"]})
        await websocket.send(json.dumps({"jsonrpc": "2.0", "id": 1, "result": 7}))
        await websocket.wait_closed()

    async with serve(target, "127.0.0.1", 0, ssl=server_ssl) as server:
        destination = server.sockets[0].getsockname()[1]

        async def proxy(reader, writer):
            opening = await reader.readuntil(b"\r\n\r\n")
            observations.append({"proxy_method": opening.split(b" ", 1)[0].decode()})
            peer_reader, peer_writer = await asyncio.open_connection("127.0.0.1", destination)
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await writer.drain()

            async def pump(source, sink):
                try:
                    while block := await source.read(65536):
                        sink.write(block)
                        await sink.drain()
                finally:
                    sink.close()

            tasks = [asyncio.create_task(pump(reader, peer_writer)),
                     asyncio.create_task(pump(peer_reader, writer))]
            pumps.extend(tasks)
            await asyncio.gather(*tasks, return_exceptions=True)

        async with await asyncio.start_server(proxy, "127.0.0.1", 0) as gateway:
            proxy_port = gateway.sockets[0].getsockname()[1]
            # These synthetic process-scoped settings exercise automatic discovery.
            # No configured proxy/credential values are printed or inspected.
            os.environ["wss_proxy"] = f"http://127.0.0.1:{proxy_port}"
            os.environ["no_proxy"] = os.environ["NO_PROXY"] = ""
            async with connector("wss://observer-probe.invalid/", ssl=client_ssl) as websocket:
                await websocket.send(json.dumps({"method": "logsSubscribe"}))
                await websocket.recv()
        await asyncio.gather(*pumps, return_exceptions=True)
    assert observations == [{"proxy_method": "CONNECT"}, {"subscription": "logsSubscribe"}]
    return {"state": "PASS", "scope": "Local verified TLS via automatic environment HTTP proxy",
            "connector": "application_default" if connector is application_connect else "library_default",
            "observations": observations, "loopback_socket_attempts": len(socket_attempts),
            "external_requests": 0, "external_sockets_guarded": True,
            "tls_verification_enabled": True}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temporary:
        print(json.dumps(asyncio.run(scenario(Path(temporary))), indent=2))
