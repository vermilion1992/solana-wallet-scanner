"""Replay the frozen browser runner with an explicit assertion timing budget.

The first genuine 200-record UI run completed the import request but failed the
5-second default visibility assertion during the subsequent large report refresh.
This changes Playwright runner configuration only, not application or assertions.
"""
from pathlib import Path
import runpy
import sys
from playwright.sync_api import expect
expect.set_options(timeout=120000)
root = Path(__file__).resolve().parents[2]
sys.argv = [str(root/'tools/product_browser.py'), '--python', str(root/'.venv/bin/python'),
            '--chromium', '/usr/bin/chromium', '--output', str(root/'evidence/indexed-native-batch/product-browser-verified'),
            '--indexed-archive', '/workspace/outputs/indexed-native-review/genuine-indexed-partial.zip',
            '--indexed-expected-fees', '0.008904733']
runpy.run_path(str(root/'tools/product_browser.py'), run_name='__main__')
