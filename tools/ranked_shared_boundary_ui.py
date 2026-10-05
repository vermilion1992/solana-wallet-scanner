#!/usr/bin/env python3
"""Offline phone/desktop capture of the honest ranked partial report. Zero provider calls."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright, expect
from scanner.mass_search.canonical_records import gta_records_from_capture
from scanner.mass_search.g3_reacquire import ALLOWED_WALLET
from scanner.mass_search.history_ingest import replay_cached_history_to_report
from scanner.storage import Store, now
from tools.screening_browser import Launcher

OUT = Path("/tmp/ranked-shared-boundary-ui")
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
CAPTURE = ROOT / "evidence/mass-wallet-funnel/ranked100-anchored-validation-live/SOURCE_RESPONSE_page0.json"
WINDOWS = {
    "report_start_inclusive": "2026-09-05T13:29:27Z",
    "report_end_exclusive": "2026-10-05T13:29:27Z",
    "acquisition_support_start_inclusive": "2026-07-07T13:29:27Z",
}


def _open_watchlist(page):
    page.get_by_role("button", name="Search", exact=True).wait_for()
    nav = page.get_by_label("Main navigation")
    if not nav.is_visible():
        page.get_by_role("button", name="Open navigation").click()
        nav = page.get_by_label("Main navigation")
    nav.get_by_role("button", name="Watchlist").click()


def _open_search(page):
    page.get_by_role("button", name="Search", exact=True).wait_for()
    nav = page.get_by_label("Main navigation")
    if not nav.is_visible():
        page.get_by_role("button", name="Open navigation").click()
        nav = page.get_by_label("Main navigation")
    nav.get_by_role("button", name="Search", exact=True).click()


data = OUT / "data"
data.mkdir()
store = Store(data)
records = gta_records_from_capture(json.loads(CAPTURE.read_text()))
replay = replay_cached_history_to_report(
    store,
    address=ALLOWED_WALLET,
    records=records,
    window_start=WINDOWS["report_start_inclusive"],
    window_end=WINDOWS["report_end_exclusive"],
    acquisition_start=WINDOWS["acquisition_support_start_inclusive"],
    corpus_kind="GENUINE_REPLAY",
    authorization_id="live-ranked100-anchored-validation-2026-10-06-mitch",
    source_id="ranked100-anchored-offline-replay",
)
store.put(
    "watchlist",
    ALLOWED_WALLET,
    {
        "address": ALLOWED_WALLET,
        "label": "ranked-100 rank 1",
        "added_at": now(),
        "source": "mass-search",
        "shortlist_rank": 1,
    },
)
report_id = replay["report_id"]
run_id = replay["run_id"]
store.close()

hooks = OUT / "hooks"
hooks.mkdir()
(hooks / "sitecustomize.py").write_text(
    "import sys\nfrom types import SimpleNamespace\nimport httpx\n"
    "def credential(*a, **k):\n    raise AssertionError('offline UI forbids credential lookup')\n"
    "sys.modules['keyring'] = SimpleNamespace(get_keyring=lambda: object(), get_password=credential, set_password=credential)\n"
    "async def forbidden(*args, **kwargs):\n    raise AssertionError('offline UI blocked an outbound provider request')\n"
    "httpx.AsyncClient.post = forbidden\nhttpx.AsyncClient.get = forbidden\n"
)
env = {k: v for k, v in os.environ.items() if k not in ("HELIUS_API_KEY", "BIRDEYE_API_KEY", "HELIUS_KEY")}
env["PYTHONPATH"] = str(hooks) + os.pathsep + str(ROOT)
chrome = "/usr/local/bin/google-chrome" if Path("/usr/local/bin/google-chrome").exists() else "/usr/bin/google-chrome"

launcher = Launcher(OUT, env)
result = {
    "report_id": report_id,
    "run_id": run_id,
    "external": [],
    "errors": [],
    "PRODUCT_READY": False,
}
try:
    launcher.start()
    pw = sync_playwright().start()
    browser = pw.chromium.launch(executable_path=chrome, headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.on("pageerror", lambda err: result["errors"].append(str(err)))
    page.on(
        "request",
        lambda req: result["external"].append(req.url)
        if not req.url.startswith(("http://127.0.0.1", "http://localhost"))
        else None,
    )
    page.goto(launcher.url)
    _open_watchlist(page)
    page.get_by_role("button", name="Latest report").click()
    page.get_by_text("Reconstructed subset / independent worksheet", exact=True).wait_for(timeout=15000)
    expect(page.get_by_text("Reconstructed subset / independent worksheet", exact=True)).to_be_visible()
    expect(page.get_by_text("PARTIAL_NO_SUPPORTED_SOL_SWAPS")).to_be_visible()
    expect(page.get_by_text("Visible transaction fees are not profit")).to_be_visible()
    page.screenshot(path=str(OUT / "01-report-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 360, "height": 640})
    page.screenshot(path=str(OUT / "01-report-mobile.png"), full_page=True)
    exported = page.request.get(f"{launcher.base}/api/export/reports/{report_id}.json")
    (OUT / "export.json").write_text(exported.text())
    result["export_status"] = exported.status
    page.set_viewport_size({"width": 1440, "height": 1000})
    _open_search(page)
    page.get_by_role("button", name="Refilter cached rows").click()
    expect(page.get_by_text("Cached refilter issued no provider calls.")).to_be_visible()
    page.screenshot(path=str(OUT / "03-refilter-desktop.png"), full_page=True)
    result["refilter_ok"] = True
    browser.close()
    pw.stop()
    launcher.stop()

    launcher.start()
    pw = sync_playwright().start()
    browser = pw.chromium.launch(executable_path=chrome, headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 360, "height": 640})
    page.goto(launcher.url)
    _open_watchlist(page)
    page.get_by_role("button", name="Latest report").click()
    expect(page.get_by_text("PARTIAL_NO_SUPPORTED_SOL_SWAPS")).to_be_visible()
    page.screenshot(path=str(OUT / "02-reopen-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.screenshot(path=str(OUT / "02-reopen-desktop.png"), full_page=True)
    browser.close()
    pw.stop()
    result["reopen_ok"] = True
    result["external_after"] = list(result["external"])
finally:
    launcher.stop()

result["external_count"] = len(result["external"])
(OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
