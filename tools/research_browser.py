#!/usr/bin/env python3
"""Actual launcher/Chromium check of Research paper tables at 1440 and 360.

Seeds two stopped synthetic paper runs in disposable storage. No live provider
calls, credentials, or paid quota. This cannot prove genuine observation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
BANNER = "OFFLINE SYNTHETIC TEST TRANSPORT · Research paper tables only"
GUARD_SOURCE = r"""
import sys
from types import SimpleNamespace
import httpx
def credential(*a, **k):
    raise AssertionError('Offline research browser forbids credential lookup')
sys.modules['keyring'] = SimpleNamespace(get_keyring=lambda: object(), get_password=credential, set_password=credential)
async def forbidden(*args, **kwargs):
    raise AssertionError('Offline research browser blocked an outbound provider request')
httpx.AsyncClient.post = forbidden
httpx.AsyncClient.get = forbidden
"""


def seed_paper_runs(data_dir):
    sys.path.insert(0, str(ROOT))
    from scanner.mass_search.universe import synthetic_address
    from scanner.paper import create_run, get_run, stop_run
    from scanner.storage import Store

    store = Store(data_dir)
    try:
        at = datetime.now(timezone.utc)
        first = create_run(store, synthetic_address(1), at=at)
        second = create_run(store, synthetic_address(3), at=at)
        for run_id, mint_index in ((first["id"], 2), (second["id"], 4)):
            run = get_run(store, run_id, at=at)
            run["positions"] = [{
                "id": "open-loss",
                "mint": synthetic_address(mint_index),
                "status": "open",
                "cost_lamports": "100010000",
                "opened_at": run["started_at"],
                "exit_unavailable": True,
            }]
            run["gaps"] = [{"reason": "subscription disconnected"}]
            store.put("paper_runs", run_id, run)
            stop_run(store, run_id, reason="user_stopped", at=at)
        return first["id"], second["id"]
    finally:
        store.close()


def run(args):
    sys.path.insert(0, str(ROOT))
    from playwright.sync_api import sync_playwright, expect
    from tools.screening_browser import Launcher

    out = args.output.absolute()
    out.mkdir(parents=True, exist_ok=False)
    result = {
        "kind": "actual-launcher-offline-synthetic-research-browser",
        "state": "INCOMPLETE",
        "software_functionality": "INCOMPLETE",
        "genuine_live_evidence": "NOT_RUN_IN_OFFLINE_BROWSER",
        "PRODUCT_READY": False,
        "cases": [],
        "limitations": [
            "Seeded stopped paper runs validate Research table/card layout, not live quotes or profitable following.",
        ],
    }
    hooks = out / "hooks"
    hooks.mkdir()
    (hooks / "sitecustomize.py").write_text(GUARD_SOURCE)
    env = {key: value for key, value in os.environ.items() if key not in ("HELIUS_API_KEY", "JUPITER_API_KEY", "JUP_API_KEY")}
    env.update(PYTHONPATH=str(hooks) + os.pathsep + str(ROOT))
    data_dir = out / "data"
    first_id, second_id = seed_paper_runs(data_dir)
    launcher = Launcher(out, env)
    try:
        launcher.start()
        pw = sync_playwright().start()
        browser = pw.chromium.launch(executable_path=args.chromium, headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors, external = [], []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on("request", lambda req: external.append(req.url) if not req.url.startswith(("http://127.0.0.1", "http://localhost")) else None)
        page.goto(launcher.url)
        page.get_by_role("button", name="Research", exact=True).click()
        expect(page.get_by_text("Saved paper observations", exact=False).first).to_be_visible(timeout=15000)
        expect(page.get_by_text("Paper positions", exact=True)).to_be_visible()
        expect(page.get_by_text("sell quote unavailable", exact=False).first).to_be_visible()
        expect(page.get_by_text("Incomplete observation", exact=False).first).to_be_visible()

        def capture(name):
            page.evaluate(
                """message => {let b=document.getElementById('synthetic-browser-test-banner');if(!b){b=document.createElement('div');b.id='synthetic-browser-test-banner';b.style.cssText='position:sticky;top:0;z-index:9999;padding:12px;background:#571a21;color:#fff;text-align:center;font:700 14px sans-serif;overflow-wrap:anywhere;max-width:100%;box-sizing:border-box';document.body.prepend(b)}b.textContent=message}""",
                BANNER,
            )
            for width, height, label in ((1440, 1000, "desktop"), (360, 640, "mobile")):
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
                      return { innerWidth: vw, scrollWidth: sw, overflow: sw > vw || scrollX !== 0, nodes };
                    }"""
                )
                result.setdefault("overflow", []).append({"name": name, "label": label, **measured})
                page.screenshot(path=str(out / f"{name}-{label}.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})

        capture("01-research-paper-tables")
        page.set_viewport_size({"width": 360, "height": 640})
        page.wait_for_timeout(350)
        expect(page.locator(".research-cards").first).to_be_visible()
        expect(page.get_by_text("sell quote unavailable", exact=False).first).to_be_visible()
        page.set_viewport_size({"width": 1440, "height": 1000})
        result["cases"].append({
            "case": "research-paper-tables",
            "state": "PASS",
            "run_ids": [first_id, second_id],
        })
        assert not errors, errors
        assert not external, external
        overflowed = [row for row in result.get("overflow", []) if row["overflow"]]
        result.update(
            state="PASS" if not overflowed else "FAILED",
            software_functionality="PASS_IN_SYNTHETIC_BROWSER_SCOPE",
            javascript_errors=errors,
            external_browser_requests=external,
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
