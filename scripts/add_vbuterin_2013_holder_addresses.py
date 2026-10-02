#!/usr/bin/env python3
"""Add holder addresses to a frozen vbuterin 2013 census record.

  python scripts/add_vbuterin_2013_holder_addresses.py historical/census/vbuterin_2013_mainnet_v0.1.json \\
      --lookup mempool-addresses.json --label mempool.space \\
      --lookup blockstream-addresses.json --label blockstream.info --run-id <workflow run>

Each --lookup is the JSON printed by address_vbuterin_2013_holdings.py. Every
holding gains ``address`` and ``spent_after_census`` (the spending TXID seen
at lookup time, or null) when all services agree; the lineage itself is not
touched. The record is rewritten in place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("record", type=Path)
    ap.add_argument("--lookup", type=Path, action="append", required=True)
    ap.add_argument("--label", action="append", required=True)
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()
    if len(args.lookup) != len(args.label):
        ap.error("give one --label per --lookup")

    record = json.loads(args.record.read_text(encoding="utf-8"))
    lookups = []
    for path in args.lookup:
        data = json.loads(path.read_text(encoding="utf-8"))
        lookups.append({(h["txid"], h["vout"]): h for h in data["holdings"]})

    disagreements, unresolved = [], []
    for g in record["geneses"]:
        for i, h in enumerate(g["holdings"]):
            key = (h["txid"], h["vout"])
            seen = [lk.get(key) for lk in lookups]
            if any(s is None for s in seen):
                unresolved.append(f"{h['txid']}:{h['vout']}")
                continue
            if len({(s["address"], s["spent_by"]) for s in seen}) != 1:
                disagreements.append({"outpoint": f"{h['txid']}:{h['vout']}",
                                      **{lbl: [s["address"], s["spent_by"]] for lbl, s in zip(args.label, seen)}})
                continue
            h = dict(h, address=seen[0]["address"], spent_after_census=seen[0]["spent_by"])
            g["holdings"][i] = {k: h[k] for k in sorted(h)}

    holdings = [h for g in record["geneses"] for h in g["holdings"]]
    record["holder_addresses"] = {
        "added_by": "scripts/address_vbuterin_2013_holdings.py, scripts/add_vbuterin_2013_holder_addresses.py",
        "workflow_run": args.run_id,
        "sources": [{"service": lbl, "result_sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                    for lbl, p in zip(args.label, args.lookup)],
        "note": ("address names the holding output as the census tracer does; spent_after_census is the spending "
                 "TXID seen at lookup time (null: still unspent). Lineages and totals are unchanged."),
        "holdings_named": sum(1 for h in holdings if "address" in h),
        "holdings_spent_after_census": sum(1 for h in holdings if h.get("spent_after_census")),
        "disagreements": disagreements,
        "unresolved": unresolved,
    }
    args.record.write_text(json.dumps(record, indent=1, sort_keys=False, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in record["holder_addresses"].items() if k != "sources"}, indent=1))
    return 1 if disagreements or unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
