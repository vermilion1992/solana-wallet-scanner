#!/usr/bin/env python3
"""Actual launcher/Chromium check of the offline Mass Search funnel.

Uses disposable storage and the fixture vertical slice. No live provider
calls, credentials, or paid quota. This cannot prove a genuine search.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
BANNER = "OFFLINE SYNTHETIC TEST TRANSPORT · Mass Search UI only"
GUARD_SOURCE = r"""
import sys
from types import SimpleNamespace
import httpx
def credential(*a, **k):
    raise AssertionError('Offline mass-search browser forbids credential lookup')
sys.modules['keyring'] = SimpleNamespace(get_keyring=lambda: object(), get_password=credential, set_password=credential)
async def forbidden(*args, **kwargs):
    raise AssertionError('Offline mass-search browser blocked an outbound provider request')
httpx.AsyncClient.post = forbidden
httpx.AsyncClient.get = forbidden
"""


def run(args):
    sys.path.insert(0, str(ROOT))
    from playwright.sync_api import sync_playwright, expect
    from tools.screening_browser import Launcher

    out = args.output.absolute()
    out.mkdir(parents=True, exist_ok=False)
    result = {
        "kind": "actual-launcher-offline-synthetic-mass-search-browser",
        "state": "INCOMPLETE",
        "software_functionality": "INCOMPLETE",
        "genuine_live_evidence": "NOT_RUN_IN_OFFLINE_BROWSER",
        "PRODUCT_READY": False,
        "cases": [],
        "limitations": [
            "Synthetic fixture slice validates Search UI mechanics, not live acquisition or profitable wallets.",
        ],
    }
    hooks = out / "hooks"
    hooks.mkdir()
    (hooks / "sitecustomize.py").write_text(GUARD_SOURCE)
    env = {key: value for key, value in os.environ.items() if key not in ("HELIUS_API_KEY", "JUPITER_API_KEY", "JUP_API_KEY")}
    env.update(PYTHONPATH=str(hooks) + os.pathsep + str(ROOT))
    launcher = Launcher(out, env)
    try:
        launcher.start()
        pw = sync_playwright().start()
        browser = pw.chromium.launch(executable_path=args.chromium, headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors, external, api_trace = [], [], []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on("request", lambda req: external.append(req.url) if not req.url.startswith(("http://127.0.0.1", "http://localhost")) else None)

        def trace(response):
            if response.url.startswith(launcher.base + "/api/"):
                api_trace.append({
                    "method": response.request.method,
                    "path": response.url.removeprefix(launcher.base),
                    "status": response.status,
                })

        page.on("response", trace)
        assert page.request.get(launcher.base + "/api/state").status == 401
        page.goto(launcher.url)
        page.get_by_role("button", name="Search", exact=True).wait_for()

        def expect_worksheet():
            expect(page.get_by_text("Reconstructed subset / independent worksheet", exact=True)).to_be_visible()
            expect(page.get_by_text("Not a wallet-wide MATCH", exact=False)).to_be_visible()
            expect(page.get_by_text("0.575 SOL", exact=False).first).to_be_visible()
            expect(page.get_by_text("30 seconds", exact=False).first).to_be_visible()
            expect(page.get_by_text("48 hours (172800 seconds)", exact=True)).to_be_visible()
            expect(page.get_by_text("A conclusion needs more evidence", exact=False)).to_be_visible()

        def expect_subset_screening():
            expect(page.get_by_text("Insufficient evidence", exact=False).first).to_be_visible()
            expect(page.locator('[data-screening-corpus="reconstructed-subset"]').first).to_be_visible()
            expect(page.get_by_text("UNRESOLVED reconstructed subset", exact=False)).to_be_visible()
            expect(page.get_by_text("not a wallet-wide MATCH", exact=False).first).to_be_visible()
            expect(page.get_by_role("button", name="Start quote-only observation", exact=True)).to_be_disabled()
            expect(page.get_by_role("button", name="Continue investigation", exact=True)).to_be_disabled()

        def expect_watchlist_subset():
            expect(page.locator('[data-watch-source="mass-search"]').first).to_be_visible()
            expect(page.get_by_text("UNRESOLVED", exact=False).first).to_be_visible()
            expect(page.locator(".subset-list-label").first).to_have_text("Reconstructed subset")
            expect(page.get_by_text("not a wallet-wide MATCH", exact=False).first).to_be_visible()
            expect(page.locator('[data-list-profit="reconstructed-subset"]').first).to_contain_text("0.575")
            expect(page.get_by_text("not started from this list", exact=False)).to_be_visible()

        def expect_results_subset():
            page.get_by_label("Data source").select_option("mass-search")
            expect(page.locator('[data-list-profit="reconstructed-subset"]').first).to_contain_text("0.575")
            expect(page.locator(".subset-list-label").first).to_have_text("Reconstructed subset")
            expect(page.get_by_text("UNRESOLVED", exact=False).first).to_be_visible()

        def capture(name, *, desktop_only=False):
            page.evaluate(
                """message => {let b=document.getElementById('synthetic-browser-test-banner');if(!b){b=document.createElement('div');b.id='synthetic-browser-test-banner';b.style.cssText='position:sticky;top:0;z-index:9999;padding:12px;background:#571a21;color:#fff;text-align:center;font:700 14px sans-serif;overflow-wrap:anywhere;max-width:100%;box-sizing:border-box';document.body.prepend(b)}b.textContent=message}""",
                BANNER,
            )
            sizes = ((1440, 1000, "desktop"),) if desktop_only else ((1440, 1000, "desktop"), (360, 640, "mobile"))
            for width, height, label in sizes:
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("scrollTo(0,0)")
                page.wait_for_timeout(350)
                measured = page.evaluate(
                    """() => {
                      const vw = innerWidth;
                      const sw = document.documentElement.scrollWidth;
                      const nodes = [...document.querySelectorAll('body *')].filter((el) => {
                        const style = getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const box = el.getBoundingClientRect();
                        return box.width > vw + 1 || box.right > vw + 8;
                      }).slice(0, 12).map((el) => ({
                        tag: el.tagName.toLowerCase(),
                        cls: String(el.className || '').slice(0, 80),
                        w: Math.round(el.getBoundingClientRect().width),
                        right: Math.round(el.getBoundingClientRect().right),
                      }));
                      return {
                        innerWidth: vw,
                        scrollWidth: sw,
                        overflow: sw > vw || scrollX !== 0,
                        nodes,
                      };
                    }"""
                )
                result.setdefault("overflow", []).append({"name": name, "label": label, **measured})
                page.screenshot(path=str(out / f"{name}-{label}.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})

        page.get_by_role("button", name="Search", exact=True).click()
        expect(page.get_by_text("Not scanned", exact=True)).to_be_visible()
        capture("01-empty")
        result["cases"].append({"case": "empty-not-scanned", "state": "PASS"})

        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/api/mass-search/vertical-slice")) as sliced:
            page.get_by_role("button", name="Run offline slice", exact=True).click()
        assert sliced.value.status == 200, sliced.value.text()
        body = sliced.value.json()
        run_id = body["run"]["run_id"]
        report_id = body["reconstruction"]["report"]["id"]
        expect(page.get_by_role("button", name="Open report", exact=True).first).to_be_visible(timeout=15000)
        expect(page.get_by_text("0.575", exact=False).first).to_be_visible()
        capture("02-populated-slice")
        result["cases"].append({"case": "offline-slice-populated", "state": "PASS", "run_id": run_id, "report_id": report_id})

        with page.expect_download() as download:
            page.get_by_role("link", name="Export run", exact=False).click()
        dest = out / "mass-search-export.json"
        shutil.copyfile(download.value.path(), dest)
        exported = json.loads(dest.read_text())
        assert exported["run"]["run_id"] == run_id
        assert exported["reports"][0]["id"] == report_id
        assert exported["reports"][0]["worksheet"]["total_profit_sol"] == "0.575"
        assert exported["reports"][0]["material_exit"]["final_hold_seconds"] == 172800
        assert exported["reports"][0]["policy"] == "UNRESOLVED"
        result["cases"].append({"case": "export-run", "state": "PASS"})

        page.get_by_role("button", name="Open report", exact=True).first.click()
        expect(page.get_by_text("Wallet report", exact=False).first).to_be_visible(timeout=15000)
        expect_worksheet()
        capture("03-opened-report")
        result["cases"].append({"case": "open-subset-report", "state": "PASS", "report_id": report_id})

        page.get_by_role("button", name="Search", exact=True).click()
        expect(page.get_by_role("button", name="Reopen report", exact=True)).to_be_visible()
        launcher.stop()
        launcher.start()
        page.goto(launcher.url)
        page.get_by_role("button", name="Search", exact=True).click()
        expect(page.get_by_role("button", name="Reopen report", exact=True)).to_be_visible(timeout=15000)
        capture("04-reopen-button-after-restart")
        page.get_by_role("button", name="Reopen report", exact=True).click()
        expect(page.get_by_text("Wallet report", exact=False).first).to_be_visible(timeout=15000)
        expect_worksheet()
        capture("05-reopened-report-after-restart")
        result["cases"].append({"case": "restart-reopen-worksheet", "state": "PASS", "report_id": report_id})

        page.get_by_role("button", name="Back to results", exact=True).click()
        page.get_by_label("Data source").select_option("mass-search")
        page.get_by_label("Sort results").select_option("profit_desc")
        expect(page.locator('[data-list-profit="reconstructed-subset"]').first).to_contain_text("0.575")
        expect(page.locator(".subset-list-label").first).to_have_text("Reconstructed subset")
        expect(page.get_by_text("0.575 SOL", exact=False).first).to_be_visible()
        expect(page.get_by_text("UNRESOLVED", exact=False).first).to_be_visible()
        expect(page.get_by_text("Not a wallet-wide MATCH", exact=False)).to_have_count(0)
        capture("06-results-subset-pnl")
        page.set_viewport_size({"width": 360, "height": 640})
        page.wait_for_timeout(350)
        expect(page.locator(".report-cards").first).to_be_visible()
        expect(page.locator('[data-list-profit="reconstructed-subset"]').first).to_contain_text("0.575")
        page.set_viewport_size({"width": 1440, "height": 1000})
        result["cases"].append({"case": "results-subset-pnl", "state": "PASS", "report_id": report_id})

        page.get_by_label("Main navigation").get_by_role("button", name="Compare", exact=True).click()
        page.locator(".compare-choice").first.click()
        expect(page.locator('[data-list-profit="reconstructed-subset"]').first).to_contain_text("0.575")
        expect(page.get_by_text("Reconstructed subset", exact=False).first).to_be_visible()
        expect(page.get_by_text("not a wallet-wide MATCH", exact=False).first).to_be_visible()
        expect(page.get_by_text("RECONSTRUCTED SUBSET", exact=False).first).to_be_visible()
        expect(page.get_by_text("0.575 SOL", exact=False).first).to_be_visible()
        capture("07-compare-subset-pnl")
        page.set_viewport_size({"width": 360, "height": 640})
        page.wait_for_timeout(350)
        expect(page.locator(".compare-cards").first).to_be_visible()
        expect(page.locator('[data-list-profit="reconstructed-subset"]').first).to_contain_text("0.575")
        expect(page.get_by_text("not a wallet-wide MATCH", exact=False).first).to_be_visible()
        page.set_viewport_size({"width": 1440, "height": 1000})
        result["cases"].append({"case": "compare-subset-pnl", "state": "PASS", "report_id": report_id})

        page.get_by_label("Main navigation").get_by_role("button", name="Research", exact=True).click()
        expect(page.get_by_text("reconstructed subset, not a wallet-wide MATCH", exact=False)).to_be_visible()
        expect(page.get_by_label("Report to screen")).to_be_visible()
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/api/screenings")) as screened:
            page.get_by_role("button", name="Screen and save assessment", exact=True).click()
        assert screened.value.status == 200, screened.value.text()
        screening = screened.value.json()
        assert screening["source"] == "mass-search"
        assert screening["result"] == "insufficient_evidence"
        assert screening["strict_qualification"]["qualified"] is False
        assert screening["strict_qualification"]["financial_policy"] == "UNRESOLVED"
        assert screening["current_eligibility"]["can_start_observation"] is False
        expect(page.get_by_text("Insufficient evidence", exact=False).first).to_be_visible(timeout=15000)
        expect_subset_screening()
        capture("09-research-screen-subset")
        page.set_viewport_size({"width": 360, "height": 640})
        page.wait_for_timeout(350)
        expect_subset_screening()
        page.set_viewport_size({"width": 1440, "height": 1000})
        result["cases"].append({
            "case": "research-screen-subset",
            "state": "PASS",
            "report_id": report_id,
            "screening_id": screening["id"],
            "result": screening["result"],
            "observation_started": False,
        })

        screening_id = screening["id"]
        launcher.stop()
        launcher.start()
        page.goto(launcher.url)
        page.get_by_label("Main navigation").get_by_role("button", name="Research", exact=True).click()
        expect(page.get_by_role("button", name="Reopen saved assessment", exact=True)).to_be_visible(timeout=15000)
        capture("10-reopen-screening-button-after-restart", desktop_only=True)
        with page.expect_response(lambda response: response.request.method == "GET" and response.url.rstrip("/").endswith("/api/screenings/" + screening_id)) as reopened:
            page.get_by_role("button", name="Reopen saved assessment", exact=True).click()
        assert reopened.value.status == 200, reopened.value.text()
        detail = reopened.value.json()
        assert detail["id"] == screening_id
        assert detail["source"] == "mass-search"
        assert detail["result"] == "insufficient_evidence"
        assert detail["strict_qualification"]["qualified"] is False
        assert detail["strict_qualification"]["financial_policy"] == "UNRESOLVED"
        assert detail["current_eligibility"]["can_start_observation"] is False
        expect_subset_screening()
        expect(page.get_by_label("Saved screening assessment")).to_contain_text("subset ·")
        capture("10-reopened-screening-after-restart")
        page.set_viewport_size({"width": 360, "height": 640})
        page.wait_for_timeout(350)
        expect_subset_screening()
        expect(page.get_by_label("Saved screening assessment")).to_contain_text("subset ·")
        page.set_viewport_size({"width": 1440, "height": 1000})
        with page.expect_download() as download:
            page.get_by_role("link", name="Export screening", exact=False).click()
        dest = out / "screening-export.json"
        shutil.copyfile(download.value.path(), dest)
        exported_screening = json.loads(dest.read_text())
        assert exported_screening["id"] == screening_id
        assert exported_screening["source"] == "mass-search"
        assert exported_screening["result"] == "insufficient_evidence"
        assert exported_screening["strict_qualification"]["financial_policy"] == "UNRESOLVED"
        assert exported_screening["strict_qualification"]["qualified"] is False
        assert exported_screening["current_eligibility"]["can_start_observation"] is False
        result["cases"].append({
            "case": "restart-reopen-screening",
            "state": "PASS",
            "report_id": report_id,
            "screening_id": screening_id,
            "result": detail["result"],
            "observation_started": False,
            "export": "screening-export.json",
        })

        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/api/watchlist")) as shortlisted:
            page.get_by_role("button", name="Save to shortlist", exact=True).click()
        assert shortlisted.value.status == 200, shortlisted.value.text()
        expect(page.get_by_role("button", name="Shortlisted", exact=True)).to_be_visible()
        expect_subset_screening()
        page.get_by_label("Main navigation").get_by_role("button", name="Watchlist").click()
        expect(page.locator('[data-watch-source="mass-search"]').first).to_be_visible(timeout=15000)
        expect_watchlist_subset()
        capture("11-watchlist-shortlist-subset")
        page.set_viewport_size({"width": 360, "height": 640})
        page.wait_for_timeout(350)
        expect_watchlist_subset()
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_label("Main navigation").get_by_role("button", name="Results").click()
        expect_results_subset()
        capture("11-results-after-shortlist")
        page.get_by_label("Main navigation").get_by_role("button", name="Research", exact=True).click()
        expect_subset_screening()
        result["cases"].append({
            "case": "shortlist-subset-watchlist-results",
            "state": "PASS",
            "report_id": report_id,
            "screening_id": screening_id,
            "observation_started": False,
        })

        launcher.stop()
        launcher.start()
        page.goto(launcher.url)
        page.get_by_label("Main navigation").get_by_role("button", name="Watchlist").click()
        expect(page.locator('[data-watch-source="mass-search"]').first).to_be_visible(timeout=15000)
        expect_watchlist_subset()
        capture("12-watchlist-after-restart")
        page.set_viewport_size({"width": 360, "height": 640})
        page.wait_for_timeout(350)
        expect_watchlist_subset()
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_label("Main navigation").get_by_role("button", name="Results").click()
        expect_results_subset()
        capture("12-results-after-restart")
        page.get_by_label("Main navigation").get_by_role("button", name="Research", exact=True).click()
        expect(page.get_by_role("button", name="Shortlisted", exact=True)).to_be_visible(timeout=15000)
        expect_subset_screening()
        capture("12-research-after-restart", desktop_only=True)
        result["cases"].append({
            "case": "restart-shortlist-loop",
            "state": "PASS",
            "report_id": report_id,
            "screening_id": screening_id,
            "loop": ["slice", "screen", "reopen-screening", "shortlist", "restart", "watchlist", "results", "research"],
            "observation_started": False,
        })

        assert not errors, errors
        assert not external, external
        overflowed = [row for row in result.get("overflow", []) if row["overflow"]]
        result.update(
            state="PASS" if not overflowed else "FAILED",
            software_functionality="PASS_IN_SYNTHETIC_BROWSER_SCOPE",
            javascript_errors=errors,
            external_browser_requests=external,
            api_trace=api_trace,
            overflowed=overflowed,
            actual_launcher=str(ROOT / "run.sh"),
            browser="Chromium " + browser.version,
        )
        if overflowed:
            result["reason"] = "horizontal overflow: " + json.dumps(overflowed)
        browser.close()
    except Exception as error:
        safe = re.sub(r"#session=[A-Za-z0-9_-]+", "#session=[redacted]", str(error))
        result.update(state="FAILED", reason=type(error).__name__ + ": " + safe)
        if "page" in locals():
            try:
                page.screenshot(path=str(out / "failure.png"), full_page=True)
                (out / "failure-dom.html").write_text(page.content())
            except Exception:
                pass
        print(result.get("reason"), file=sys.stderr)
    finally:
        if "pw" in locals():
            pw.stop()
        launcher.stop()
        result["launcher_stopped"] = True
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return 0 if result["state"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chromium", default="/usr/local/bin/google-chrome")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
