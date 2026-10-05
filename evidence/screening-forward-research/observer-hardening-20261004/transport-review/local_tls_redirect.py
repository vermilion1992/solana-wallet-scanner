"""Loopback-only websockets 16 redirect probe. No provider or credential reads.

An ephemeral local certificate establishes verified wss on two local origins.
The first responds 302; the second records whether it received logsSubscribe.
Compare the installed library with the application's default connector.
"""
import asyncio
import json
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from scanner.observer import connect as application_connect
from websockets.asyncio.client import connect as library_connect
from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response


async def scenario(directory):
    certificate, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(certificate), "-days", "1",
        "-subj", "/CN=localhost", "-addext",
        "subjectAltName=DNS:localhost,IP:127.0.0.1",
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    server_ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ssl.load_cert_chain(certificate, key)
    client_ssl = ssl.create_default_context(cafile=str(certificate))
    results = []
    for name, connector in (("library_default", library_connect),
                            ("application_default", application_connect)):
        received = []

        async def destination(socket):
            received.append(json.loads(await socket.recv()))
            await socket.send(json.dumps({"jsonrpc": "2.0", "id": 1, "result": 7}))
            await socket.wait_closed()

        async with serve(destination, "127.0.0.1", 0, ssl=server_ssl) as target:
            target_port = target.sockets[0].getsockname()[1]

            def redirect(connection, request):
                return Response(302, "Found", Headers({
                    "Location": f"wss://localhost:{target_port}/redirected",
                }), b"")

            async with serve(lambda socket: None, "127.0.0.1", 0, ssl=server_ssl,
                             process_request=redirect) as source:
                source_port = source.sockets[0].getsockname()[1]
                outcome, final_path = "redirect_followed", None
                try:
                    async with connector(f"wss://localhost:{source_port}/fixed",
                                         proxy=None, ssl=client_ssl) as socket:
                        final_path = socket.request.path
                        await socket.send(json.dumps({
                            "jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                            "params": [{"mentions": ["wallet-public-address"]},
                                       {"commitment": "confirmed"}],
                        }))
                        await socket.recv()
                except InvalidStatus:
                    outcome = "redirect_rejected"
                results.append({
                    "connector": name, "outcome": outcome,
                    "tls_verification_enabled": True,
                    "cross_origin": source_port != target_port,
                    "final_path": final_path,
                    "redirected_destination_subscriptions": len(received),
                })
    return {"scope": "Local verified TLS websocket probe; no external requests",
            "results": results}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temporary:
        print(json.dumps(asyncio.run(scenario(Path(temporary))), indent=2))
