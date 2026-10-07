"""Independent recon vs app reports. Zero live provider calls."""
import json
import sys
from decimal import Decimal
from pathlib import Path

REPO = Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace")
DATA = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/research-search-b-appdata")
OUT = Path(sys.argv[3] if len(sys.argv) > 3 else DATA / "recon")
sys.path.insert(0, str(REPO))

from tools.independent_capture_reconciliation import reconcile_address
from scanner.storage import Store

ing = json.loads((DATA / "INGEST_RESULT.json").read_text()) if (DATA / "INGEST_RESULT.json").exists() else json.loads(Path(sys.argv[4]).read_text()) if len(sys.argv) > 4 else None
if ing is None:
    raise SystemExit("INGEST_RESULT.json not found")

OUT.mkdir(parents=True, exist_ok=True)
store = Store(DATA)
summary = {}
for addr, res in ing["results"].items():
    indep = reconcile_address(addr)
    report = store.get("reports", res["report_id"]) if res.get("report_id") else None
    by_asset = ((report or {}).get("by_quote_asset") or ((report or {}).get("worksheet") or {}).get("by_quote_asset") or {})
    cmp = {}
    for asset, fifo in (indep.get("fifo") or {}).items():
        app_ws = by_asset.get(asset) or {}
        key = "total_profit_usdc" if asset == "USDC" else "total_profit_sol"
        app_total = app_ws.get(key)
        app_sales = app_ws.get("sale_net_profit_usdc" if asset == "USDC" else "sale_net_profit_sol") or []
        app_rows = {((row.get("signature"), row.get("split_part") or "matched")): row for row in (app_ws.get("sale_rows") or [])}
        indep_sales = fifo["known_cost_sells"]
        same_total = (
            app_total not in (None, "")
            and fifo.get("total_profit") not in (None, "")
            and Decimal(str(app_total)).quantize(Decimal("1e-9")) == Decimal(str(fifo["total_profit"]))
        )
        per_sale = True
        for sale in indep_sales:
            app_sale = app_rows.get((sale["signature"], sale.get("split_part") or "matched"))
            if app_sale is None or Decimal(str(app_sale["net_profit"])).quantize(Decimal("1e-9")) != Decimal(str(sale["net_profit"])):
                per_sale = False
                break
        if not indep_sales and not app_sales:
            status = "BOTH_EMPTY"
        elif same_total and per_sale:
            status = "AGREE"
        elif not app_sales and indep_sales:
            status = "APP_MISSING"
        else:
            status = "DISAGREE"
        cmp[asset] = {
            "independent_total": fifo.get("total_profit"),
            "app_total": app_total,
            "independent_known_cost_sells": len(indep_sales),
            "app_sales": len(app_sales),
            "independent_unresolved_basis_sales": len(fifo.get("unresolved_basis_sales") or []),
            "independent_open_lots": len(fifo.get("open_lots") or []),
            "per_sale": per_sale,
            "status": status,
        }
    out = {
        "kind": "independent-capture-reconciliation-v1",
        "imports_app_accounting": False,
        "wallet": addr,
        "fifo": indep.get("fifo"),
        "conversions": indep.get("conversions"),
        "unsupported_tx_count": indep.get("unsupported_tx_count"),
        "app_report_id": res.get("report_id"),
        "app_error": res.get("error"),
        "comparison": cmp,
        "PRODUCT_READY": False,
    }
    (OUT / f"{addr}.json").write_text(json.dumps(out, indent=2) + "\n")
    summary[addr] = {"app_error": res.get("error"), "comparison": cmp, "unsupported_tx_count": indep.get("unsupported_tx_count")}
store.close()
(OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
for addr, row in summary.items():
    print(addr[:6], row["app_error"] or "", json.dumps(row["comparison"]))
