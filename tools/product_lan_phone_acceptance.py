#!/usr/bin/env python3
"""Reach the opt-in LAN launcher from a non-loopback client at phone width."""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import expect, sync_playwright
from scanner.__main__ import discover_lan_ipv4

OUT = Path(os.environ.get("PRODUCT_LAN_OUT", "/tmp/product-lan-phone"))
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
PHONE = {"width": 390, "height": 844}


def _free_port():
    with socket.socket() as sock:
        sock.bind((discover_lan_ipv4(), 0))
        return sock.getsockname()[1]


data = OUT / "data"
data.mkdir()
hooks = OUT / "hooks"
hooks.mkdir()
(hooks / "sitecustomize.py").write_text(
    "import sys\nfrom types import SimpleNamespace\nimport httpx\n"
    "def credential(*a, **k):\n    raise AssertionError('LAN UI forbids credential lookup')\n"
    "sys.modules['keyring'] = SimpleNamespace(get_keyring=lambda: object(), get_password=credential, set_password=credential)\n"
    "async def forbidden(*args, **kwargs):\n    raise AssertionError('LAN UI blocked an outbound provider request')\n"
    "httpx.AsyncClient.post = forbidden\nhttpx.AsyncClient.get = forbidden\n"
)
env = {k: v for k, v in os.environ.items() if k not in ("HELIUS_API_KEY", "BIRDEYE_API_KEY", "HELIUS_KEY")}
env["PYTHONPATH"] = str(hooks) + os.pathsep + str(ROOT)
port = _free_port()
lan_ip = discover_lan_ipv4()
assert not lan_ip.startswith("127.")
chrome = "/usr/local/bin/google-chrome" if Path("/usr/local/bin/google-chrome").exists() else "/usr/bin/google-chrome"
command = [str(ROOT / "run.sh"), "--lan", "--no-browser", "--port", str(port), "--data-dir", str(data)]
server = subprocess.Popen(
    command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
)
log = []
lines = queue.Queue()

def drain():
    for line in server.stdout:
        redacted = re.sub(r"#session=[A-Za-z0-9_-]+", "#session=[redacted]", line.rstrip())
        log.append(redacted)
        (OUT / "launcher.log").write_text("\n".join(log) + "\n")
        lines.put(line)

threading.Thread(target=drain, daemon=True).start()
url = None
deadline = time.monotonic() + 40
while time.monotonic() < deadline:
    if server.poll() is not None:
        raise AssertionError("LAN launcher exited: " + "; ".join(log[-8:]))
    try:
        line = lines.get(timeout=0.5)
    except queue.Empty:
        continue
    match = re.search(r"http://(\d+\.\d+\.\d+\.\d+):\d+/#session=[A-Za-z0-9_-]+", line)
    if match:
        url = match.group(0)
        break
if not url:
    raise AssertionError("LAN launcher did not print a phone URL")
host = url.split("/")[2].split(":")[0]
assert host != "127.0.0.1"
assert host != "localhost"
base = url.split("/#")[0]
result = {
    "kind": "product-lan-phone-acceptance",
    "lan_ip": host,
    "loopback": False,
    "external": [],
    "errors": [],
    "PRODUCT_READY": False,
}
try:
    pw = sync_playwright().start()
    browser = pw.chromium.launch(executable_path=chrome, headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport=PHONE)
    page.on("pageerror", lambda err: result["errors"].append(str(err)))
    page.on(
        "request",
        lambda req: result["external"].append(req.url)
        if not req.url.startswith(("http://127.0.0.1", "http://localhost", f"http://{host}"))
        else None,
    )
    unauth = page.request.get(f"{base}/api/state")
    assert unauth.status == 401
    page.goto(url)
    page.get_by_role("button", name="Search", exact=True).wait_for()
    opener = page.get_by_role("button", name="Open navigation")
    if opener.count():
        opener.click()
    page.get_by_label("Main navigation").get_by_role("button", name="Search", exact=True).click()
    closer = page.get_by_role("button", name="Close navigation")
    if closer.count():
        closer.click()
    expect(page.get_by_text("Ranked-100 cached shortlist")).to_be_visible()
    page.screenshot(path=str(OUT / "lan-phone.png"), full_page=False)
    shots = Path("/opt/cursor/artifacts/screenshots")
    shots.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUT / "lan-phone.png", shots / "phone_lan_same_wifi.png")
    inst = page.request.get(f"{base}/api/mass-search/instrumentation")
    assert inst.status == 200
    assert inst.json()["backend_provider_calls"] == 0
    browser.close()
    pw.stop()
    result["state"] = "PASS" if not result["external"] and not result["errors"] else "FAILED"
    result["unauthenticated_status"] = 401
    result["provider_calls"] = 0
finally:
    if server.poll() is None:
        server.send_signal(signal.SIGTERM)
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)

(OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
sys.exit(0 if result.get("state") == "PASS" else 1)
