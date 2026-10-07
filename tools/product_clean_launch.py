#!/usr/bin/env python3
"""Clean-launch journey from ./run.sh only. Fresh data dir, then existing dir, then LAN.

390×844 Playwright Chromium emulation (labelled). Zero provider calls.
"""
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
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import expect, sync_playwright

from scanner.mass_search.g3_reacquire import ALLOWED_WALLET

OUT = Path(os.environ.get("PRODUCT_CLEAN_LAUNCH_OUT", "/tmp/product-clean-launch"))
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
SHOTS = Path("/opt/cursor/artifacts/screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)
PHONE = {"width": 390, "height": 844}
SYNTH_USDC = "SynthEngUSDC11111111111111111111111111112"


def _free_port(host="127.0.0.1"):
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def _open_nav(page, name):
    page.get_by_role("button", name="Search", exact=True).wait_for()
    if page.viewport_size and page.viewport_size["width"] <= 700:
        opener = page.get_by_role("button", name="Open navigation")
        if opener.count():
            opener.click()
    nav = page.get_by_label("Main navigation")
    nav.get_by_role("button", name=name, exact=True).click()
    closer = page.get_by_role("button", name="Close navigation")
    if closer.count():
        closer.click()


def _shot(page, name):
    dest = OUT / f"{name}.png"
    page.screenshot(path=str(dest), full_page=False)
    shutil.copyfile(dest, SHOTS / f"{name}.png")
    return dest


def _offline_env():
    hooks = OUT / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "sitecustomize.py").write_text(
        "import sys\nfrom types import SimpleNamespace\nimport httpx\n"
        "def credential(*a, **k):\n    raise AssertionError('clean launch forbids credential lookup')\n"
        "sys.modules['keyring'] = SimpleNamespace(get_keyring=lambda: object(), get_password=credential, set_password=credential)\n"
        "async def forbidden(*args, **kwargs):\n    raise AssertionError('clean launch blocked an outbound provider request')\n"
        "httpx.AsyncClient.post = forbidden\nhttpx.AsyncClient.get = forbidden\n"
    )
    env = {k: v for k, v in os.environ.items() if k not in ("HELIUS_API_KEY", "BIRDEYE_API_KEY", "HELIUS_KEY")}
    env["PYTHONPATH"] = str(hooks) + os.pathsep + str(ROOT)
    return env


def start_run_sh(*, data_dir, port, lan=False, host="127.0.0.1"):
    env = _offline_env()
    command = [str(ROOT / "run.sh"), "--no-browser", "--port", str(port), "--data-dir", str(data_dir)]
    if lan:
        command.insert(1, "--lan")
    server = subprocess.Popen(
        command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    log = []
    lines = queue.Queue()

    def drain():
        for line in server.stdout:
            redacted = re.sub(r"#session=[A-Za-z0-9_-]+", "#session=[redacted]", line.rstrip())
            log.append(redacted)
            (OUT / ("lan-launcher.log" if lan else "loopback-launcher.log")).write_text("\n".join(log) + "\n")
            lines.put(line)

    threading.Thread(target=drain, daemon=True).start()
    url = None
    pattern = (
        r"http://(\d+\.\d+\.\d+\.\d+):\d+/#session=[A-Za-z0-9_-]+"
        if lan
        else r"http://127\.0\.0\.1:\d+/#session=[A-Za-z0-9_-]+"
    )
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise AssertionError("run.sh exited: " + "; ".join(log[-8:]))
        try:
            line = lines.get(timeout=0.5)
        except queue.Empty:
            continue
        match = re.search(pattern, line)
        if match:
            url = match.group(0)
            break
    if not url:
        raise AssertionError("run.sh did not print a session URL")
    return server, url, log


def stop_run_sh(server):
    if server.poll() is None:
        server.send_signal(signal.SIGINT)
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
    time.sleep(0.5)


result = {
    "kind": "product-clean-launch-v1",
    "launcher": "./run.sh",
    "emulation": "Playwright Chromium 390x844 labelled browser emulation, not a physical phone",
    "cases": {},
    "external": [],
    "errors": [],
    "PRODUCT_READY": False,
}
data = OUT / "data"
data.mkdir()
chrome = "/usr/local/bin/google-chrome" if Path("/usr/local/bin/google-chrome").exists() else "/usr/bin/google-chrome"
port = _free_port()
server = None
try:
    server, url, _log = start_run_sh(data_dir=data, port=port)
    base = url.split("/#")[0]
    result["fresh_url_host"] = "127.0.0.1"
    pw = sync_playwright().start()
    browser = pw.chromium.launch(executable_path=chrome, headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport=PHONE)
    page.on("pageerror", lambda err: result["errors"].append(str(err)))
    page.on(
        "request",
        lambda req: result["external"].append(req.url)
        if not req.url.startswith(("http://127.0.0.1", "http://localhost"))
        else None,
    )
    assert page.request.get(f"{base}/api/state").status == 401
    page.goto(url)
    _open_nav(page, "Search")
    expect(page.get_by_text("Ranked-100 cached shortlist")).to_be_visible()
    expect(page.locator("[data-ranked-workflow]")).to_be_visible()
    expect(page.get_by_text("History required — not analysed").first).to_be_visible()
    expect(page.locator("[data-research-screen]")).to_contain_text("inconclusive")
    expect(page.locator("[data-research-screen]")).to_contain_text("not evaluated")
    page.get_by_role("button", name="Acquire history").click()
    expect(page.locator("[data-acquire-block]")).to_contain_text("blocked")
    page.get_by_label("Minimum provider trade count").fill("20")
    page.get_by_role("button", name="Save filters").click()
    expect(page.locator("[data-filters-saved]")).to_be_visible()
    page.get_by_label("Shortlist", exact=False).first.check()
    page.locator("[data-ranked-cards]").first.scroll_into_view_if_needed()
    _shot(page, "clean-01-ranked100-phone")
    result["cases"]["fresh_open_browse_filter_shortlist"] = "PASS"

    page.get_by_role("button", name="Analyse available + fixtures").click()
    page.locator("[data-batch-progress=completed]").wait_for(timeout=120000)
    expect(page.locator("[data-batch-status=analysed]").first).to_be_visible()
    expect(page.locator("[data-batch-status=history_required]").first).to_be_visible()
    _shot(page, "clean-02-batch-phone")
    result["cases"]["fresh_analyse"] = "PASS"

    page.get_by_role("button", name="Open report").first.click()
    page.get_by_text("Reconstructed subset / independent worksheet", exact=True).wait_for(timeout=15000)
    expect(page.locator("[data-subset-worksheet]").get_by_text("376.0281 USDC").first).to_be_visible()
    expect(page.locator("[data-result-scope]")).to_contain_text("conditional on captured inventory")
    expect(page.locator("[data-analytics-trades], [data-subset-trades]").first).to_be_visible()
    _shot(page, "clean-03-report-phone")
    reports = page.request.get(f"{base}/api/state?report_view=summary").json()["reports"]
    mass = [row for row in reports if row.get("source") == "mass-search"]
    genuine = next(row for row in mass if row.get("address") == ALLOWED_WALLET)
    exported = page.request.get(f"{base}/api/export/reports/{genuine['id']}.json")
    assert exported.status == 200
    body = exported.json()
    assert body["worksheet"]["total_profit_usdc"] == "376.028087"
    assert Decimal(body["worksheet"]["total_profit_usdc"]) == Decimal("376.028087")
    assert body["visible_report"] is True
    synth = next((row for row in mass if row.get("address") == SYNTH_USDC), None)
    if synth:
        _open_nav(page, "Search")
        page.get_by_label("Compare left report").select_option(genuine["id"])
        page.get_by_label("Compare right report").select_option(synth["id"])
        page.get_by_role("button", name="Compare saved reports").click()
        expect(page.locator("[data-research-compare]")).to_contain_text("Mismatches")
        _shot(page, "clean-03b-compare-phone")
    result["cases"]["fresh_inspect_compare_export"] = "PASS"
    result["export_report_id"] = genuine["id"]
    browser.close()
    pw.stop()
    stop_run_sh(server)
    server = None
    port = _free_port()

    server, url, _log = start_run_sh(data_dir=data, port=port)
    base = url.split("/#")[0]
    pw = sync_playwright().start()
    browser = pw.chromium.launch(executable_path=chrome, headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport=PHONE)
    page.on(
        "request",
        lambda req: result["external"].append(req.url)
        if not req.url.startswith(("http://127.0.0.1", "http://localhost"))
        else None,
    )
    assert page.request.get(f"{base}/api/state").status == 401
    page.goto(url)
    _open_nav(page, "Search")
    expect(page.get_by_text("Saved subset reports")).to_be_visible()
    page.get_by_role("button", name="Reopen report").first.click()
    expect(page.get_by_text("Research profile")).to_be_visible()
    expect(page.locator("[data-result-scope]")).to_contain_text("conditional on captured inventory")
    again = page.request.get(f"{base}/api/export/reports/{result['export_report_id']}.json").json()
    assert again["visible_report"] is True
    assert again["worksheet"]["total_profit_usdc"] == "376.028087"
    _shot(page, "clean-04-reopen-existing-dir")
    result["cases"]["existing_dir_restart_reopen_export"] = "PASS"
    browser.close()
    pw.stop()
    stop_run_sh(server)
    server = None

    from scanner.__main__ import discover_lan_ipv4
    lan_ip = discover_lan_ipv4()
    lan_port = _free_port(lan_ip)
    server, url, _log = start_run_sh(data_dir=data, port=lan_port, lan=True, host=lan_ip)
    host = url.split("/")[2].split(":")[0]
    assert host == lan_ip and not host.startswith("127.")
    base = url.split("/#")[0]
    pw = sync_playwright().start()
    browser = pw.chromium.launch(executable_path=chrome, headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport=PHONE)
    unauth = page.request.get(f"{base}/api/state")
    assert unauth.status == 401
    page.goto(url)
    _open_nav(page, "Search")
    expect(page.get_by_text("Ranked-100 cached shortlist")).to_be_visible()
    expect(page.get_by_text("Saved subset reports")).to_be_visible()
    _shot(page, "clean-05-lan-phone")
    result["cases"]["lan_existing_dir"] = "PASS"
    result["lan_ip"] = host
    browser.close()
    pw.stop()
    result["cases"]["zero_provider_calls"] = "PASS" if not result["external"] else "FAIL"
finally:
    if server is not None:
        stop_run_sh(server)

result["external_count"] = len(result["external"])
result["tested_commit"] = os.popen("git -C %s rev-parse HEAD" % ROOT).read().strip()
result["state"] = "PASS" if all(value == "PASS" for value in result["cases"].values()) and not result["external"] else "FAILED"
(OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
sys.exit(0 if result["state"] == "PASS" else 1)
