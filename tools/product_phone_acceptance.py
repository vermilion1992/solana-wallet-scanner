#!/usr/bin/env python3
"""Phone-width acceptance A-H for the ranked-100 product path. Zero provider calls."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import expect, sync_playwright
from scanner.mass_search.g3_reacquire import ALLOWED_WALLET
from scanner.mass_search.live_g1 import independent_fifo_worksheet
from tools.screening_browser import Launcher

OUT = Path(os.environ.get("PRODUCT_PHONE_OUT", "/tmp/product-phone-acceptance"))
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
SHOTS = Path("/opt/cursor/artifacts/screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)

SYNTH_USDC = "SynthEngUSDC11111111111111111111111111112"
PHONE = {"width": 390, "height": 844}


def _open_nav(page, name, *, exact=False):
    page.get_by_role("button", name="Search", exact=True).wait_for()
    if page.viewport_size and page.viewport_size["width"] <= 700:
        opener = page.get_by_role("button", name="Open navigation")
        if opener.count():
            opener.click()
    nav = page.get_by_label("Main navigation")
    nav.get_by_role("button", name=name, exact=exact).click()
    closer = page.get_by_role("button", name="Close navigation")
    if closer.count():
        closer.click()


def _shot(page, name):
    dest = OUT / f"{name}.png"
    page.screenshot(path=str(dest), full_page=False)
    shutil.copyfile(dest, SHOTS / f"{name}.png")
    return dest


data = OUT / "data"
data.mkdir()
from scanner.storage import Store

store = Store(data)
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
    "kind": "product-phone-acceptance-ah",
    "cases": {},
    "external": [],
    "errors": [],
    "PRODUCT_READY": False,
    "provider_calls": 0,
}
try:
    launcher.start()
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
    assert page.request.get(f"{launcher.base}/api/state").status == 401
    page.goto(launcher.url)
    _open_nav(page, "Search", exact=True)
    expect(page.get_by_text("Ranked-100 cached shortlist")).to_be_visible()
    expect(page.locator("[data-ranked-workflow]")).to_be_visible()
    expect(page.get_by_text("History required — not analysed").first).to_be_visible()
    expect(page.locator("[data-phone-access]")).to_be_visible()
    page.get_by_label("Minimum provider trade count").fill("20")
    page.get_by_role("button", name="Save filters").click()
    expect(page.locator("[data-filters-saved]")).to_be_visible()
    page.get_by_label("Shortlist", exact=False).first.check()
    expect(page.get_by_text("Your shortlist only")).to_be_visible()
    page.locator("[data-ranked-cards]").first.scroll_into_view_if_needed()
    _shot(page, "01-ranked100-phone")
    result["cases"]["A_ranked_filter_shortlist"] = "PASS"

    page.get_by_role("button", name="Analyse available + fixtures").click()
    page.locator("[data-batch-progress=completed]").wait_for(timeout=120000)
    expect(page.get_by_text("History required — not analysed").first).to_be_visible()
    expect(page.locator("[data-batch-status=analysed]").first).to_be_visible()
    expect(page.locator("[data-batch-status=history_required]").first).to_be_visible()
    page.locator("[data-batch-progress]").scroll_into_view_if_needed()
    _shot(page, "02-batch-phone")
    result["cases"]["B_batch_genuine_fixtures_no_history"] = "PASS"

    page.get_by_role("button", name="Open report").first.click()
    page.get_by_text("Reconstructed subset / independent worksheet", exact=True).wait_for(timeout=15000)
    expect(page.locator("[data-subset-worksheet]").get_by_text("376.0281 USDC").first).to_be_visible()
    expect(page.locator("[data-wallet-analytics]")).to_be_visible()
    expect(page.get_by_text("n=1 is one completed position, not a wallet-wide median")).to_be_visible()
    expect(page.get_by_text("USDC results exclude SOL fees")).to_be_visible()
    expect(page.locator("[data-usdc-excludes-sol-fees]")).to_be_visible()
    page.locator("[data-subset-worksheet]").scroll_into_view_if_needed()
    _shot(page, "03-report-phone")
    page.locator("[data-wallet-analytics]").scroll_into_view_if_needed()
    _shot(page, "03b-analytics-phone")
    result["cases"]["C_genuine_baseline_visible"] = "PASS"

    reports = page.request.get(f"{launcher.base}/api/state?report_view=summary").json()["reports"]
    mass = [row for row in reports if row.get("source") == "mass-search"]
    assert mass, "expected saved mass-search reports"
    genuine = next(row for row in mass if row.get("address") == ALLOWED_WALLET)
    exported = page.request.get(f"{launcher.base}/api/export/reports/{genuine['id']}.json")
    assert exported.status == 200
    body = exported.json()
    assert body["worksheet"]["total_profit_usdc"] == "376.028087"
    assert body["funnel"]["A"]["state"] == "YES"
    assert body["funnel"]["B"]["state"] == "PARTIAL"
    assert body["funnel"]["C"]["state"] == "NOT_EVALUATED"
    assert body["research_profile"]["safe_to_copy"] is False
    synth = next((row for row in mass if row.get("address") == SYNTH_USDC), None)
    if synth:
        _open_nav(page, "Search", exact=True)
        page.get_by_label("Compare left report").select_option(genuine["id"])
        page.get_by_label("Compare right report").select_option(synth["id"])
        page.get_by_role("button", name="Compare saved reports").click()
        expect(page.locator("[data-research-compare]")).to_be_visible()
        expect(page.locator("[data-research-compare]")).to_contain_text("376.028087")
        result["compare_status"] = 200
        _shot(page, "03c-compare-phone")
    g1 = independent_fifo_worksheet([
        {"kind": "buy", "units": "100", "consideration_sol": "1", "wallet_fee_sol": "0.01"},
        {"kind": "sell", "units": "50", "consideration_sol": "0.8", "wallet_fee_sol": "0.005"},
        {"kind": "sell", "units": "45", "consideration_sol": "0.72", "wallet_fee_sol": "0.005"},
        {"kind": "sell", "units": "5", "consideration_sol": "0.08", "wallet_fee_sol": "0.005"},
    ])
    assert g1["total_profit_sol"].startswith("0.575")
    result["cases"]["D_export_and_g1_agree"] = "PASS"

    _open_nav(page, "Search", exact=True)
    expect(page.get_by_text("Budget / live collection")).to_be_visible()
    expect(page.get_by_role("button", name="Request live spend")).to_be_disabled()
    gate = page.request.get(f"{launcher.base}/api/mass-search/acquisition-gate").json()
    assert gate["status"]["allowed"] is False
    assert gate["attempt"]["would_contact_provider"] is False
    inst = page.request.get(f"{launcher.base}/api/mass-search/instrumentation").json()
    assert inst["backend_provider_calls"] == 0
    result["cases"]["E_auth_and_disabled_budget"] = "PASS"
    result["cases"]["G_auth_gate"] = "PASS"

    page.reload()
    _open_nav(page, "Search", exact=True)
    expect(page.get_by_text("Filters saved locally").or_(page.get_by_text("Ranked-100 cached shortlist"))).to_be_visible()
    expect(page.get_by_text("Saved subset reports")).to_be_visible()
    page.get_by_text("Saved subset reports").scroll_into_view_if_needed()
    _shot(page, "04-reopen-phone")
    result["cases"]["F_refresh_persistence"] = "PASS"

    browser.close()
    pw.stop()
    launcher.stop()

    launcher.start()
    pw = sync_playwright().start()
    browser = pw.chromium.launch(executable_path=chrome, headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport=PHONE)
    page.on(
        "request",
        lambda req: result["external"].append(req.url)
        if not req.url.startswith(("http://127.0.0.1", "http://localhost"))
        else None,
    )
    page.goto(launcher.url)
    _open_nav(page, "Search", exact=True)
    expect(page.get_by_text("Saved subset reports")).to_be_visible()
    page.get_by_role("button", name="Reopen report").first.click()
    expect(page.get_by_text("Research profile")).to_be_visible()
    target = page.locator("[data-wallet-analytics], [data-subset-worksheet]").first
    target.scroll_into_view_if_needed()
    _shot(page, "05-restart-reopen-phone")
    result["cases"]["F_restart_reopen"] = "PASS"
    browser.close()
    pw.stop()
    result["cases"]["H_zero_provider_calls"] = "PASS" if not result["external"] else "FAIL"
finally:
    launcher.stop()

result["external_count"] = len(result["external"])
result["tested_commit"] = os.popen("git -C %s rev-parse HEAD" % ROOT).read().strip()
result["state"] = "PASS" if all(value == "PASS" for value in result["cases"].values()) and not result["external"] else "FAILED"
(OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
sys.exit(0 if result["state"] == "PASS" else 1)
