#!/usr/bin/env python3
"""390x844 Playwright phone-sized emulation of the rebuilt UI. Offline only."""
from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

import uvicorn
from playwright.sync_api import expect, sync_playwright

from scanner.app import create_app
from scanner.mass_search.capture_catalog import genuine_captured_addresses
from scanner.mass_search.workflow import replay_captured_wallet
from scanner.storage import Store

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/screenshots"
DATA = Path("/tmp/phone-ui-verify-d961824")
TOKEN = "phone-ui-verify-token"
PORT = 8768
HOST = "127.0.0.1"
CCCS = "CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU"
A6PS = "A6PSQFRfv93hoAn1LhQGRT2dYQtjDKX6SE2vN9MEvbot"
W58 = "58PWvekDbHVPFB9FXGQrpumHD16NRajahkYLHiTvxvDL"


def preload():
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)
    store = Store(DATA)
    ids = {}
    for address in sorted(genuine_captured_addresses()):
        result = replay_captured_wallet(store, address, force=True)
        ids[address] = (result.get("report") or {}).get("id")
    store.close()
    return ids


def start_server():
    app = create_app(DATA, TOKEN, allowed_hosts=(HOST, "localhost"))
    config = uvicorn.Config(app, host=HOST, port=PORT, reload=False, workers=1,
                            proxy_headers=False, server_header=False, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server


def nav(page, name):
    page.get_by_role("button", name="Search", exact=True).wait_for()
    opener = page.get_by_role("button", name="Open navigation")
    if opener.count():
        opener.click()
    page.get_by_label("Main navigation").get_by_role("button", name=name, exact=True).click()
    closer = page.get_by_role("button", name="Close navigation")
    if closer.count() and closer.is_visible():
        closer.click()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ids = preload()
    start_server()
    base = f"http://{HOST}:{PORT}"
    url = f"{base}/#session={TOKEN}"
    res = {
        "errors": [],
        "shots": [],
        "viewport": "390x844 Chromium phone-sized browser emulation, not a physical phone",
        "texts": {},
        "PRODUCT_READY": False,
    }

    def shot(page, name):
        path = OUT / f"{name}.png"
        page.screenshot(path=str(path), full_page=False)
        res["shots"].append(str(path))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.on("pageerror", lambda error: res["errors"].append(str(error)))
        res["unauth_state_status"] = page.request.get(f"{base}/api/state").status
        page.goto(url)
        nav(page, "Search")
        expect(page.get_by_text("Ranked-100 cached shortlist")).to_be_visible()
        page.wait_for_timeout(1500)
        cards = page.locator("[data-ranked-cards]")
        if cards.count():
            cards.first.scroll_into_view_if_needed()
            page.wait_for_timeout(400)
        shot(page, "phone-01-ranked-list")
        screen = page.locator("[data-research-screen]")
        if screen.count():
            screen.first.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            shot(page, "phone-02-research-screen-qualification-levels")
            res["texts"]["research_screen"] = screen.first.inner_text()[:2000]
        cards = page.locator("[data-ranked-cards]")
        res["ranked_cards"] = cards.count()
        left = ids[CCCS]
        right = ids[A6PS]
        page.get_by_label("Compare left report").select_option(left)
        page.get_by_label("Compare right report").select_option(right)
        page.get_by_role("button", name="Compare saved reports").click()
        compare = page.locator("[data-research-compare]")
        expect(compare).to_be_visible()
        compare.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        shot(page, "phone-05-compare")
        res["texts"]["compare"] = compare.inner_text()[:2500]

        for address, short, extra in (
            (CCCS, "CccS", "[data-verified-sensitivity]"),
            (A6PS, "A6PS", "[data-wallet-analytics], .research-profile"),
            (W58, "58PW", "[data-independently-audited], .research-profile"),
        ):
            nav(page, "Search")
            page.wait_for_timeout(400)
            row = page.locator("[data-ranked-cards] li").filter(has_text=address[:6])
            if row.count():
                row.first.scroll_into_view_if_needed()
                row.first.get_by_role("button", name="Open report").click()
            else:
                saved = page.locator(".mass-search-saved li").filter(has_text=address[:4]).first
                saved.scroll_into_view_if_needed()
                saved.get_by_role("button", name="Reopen report").click()
            page.get_by_text("Research profile").first.wait_for(timeout=15000)
            page.wait_for_timeout(800)
            shot(page, f"phone-03-report-{short}")
            loc = page.locator(extra).first
            if loc.count():
                loc.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                shot(page, f"phone-04-report-{short}-detail")
                res["texts"][f"{short}-detail"] = loc.inner_text()[:1500]
        browser.close()

    (OUT / "PHONE_UI_VERIFY.json").write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "unauth_state_status": res["unauth_state_status"],
        "errors": res["errors"],
        "shots": res["shots"],
        "research_screen": (res["texts"].get("research_screen") or "")[:400],
        "cccs": (res["texts"].get("CccS-detail") or "")[:400],
        "a6ps": (res["texts"].get("A6PS-detail") or "")[:400],
    }, indent=2))
    if res["unauth_state_status"] != 401:
        raise SystemExit("unauthenticated /api/state must be 401")
    if res["errors"]:
        raise SystemExit(f"page errors: {res['errors']}")


if __name__ == "__main__":
    main()
