#!/usr/bin/env python3
"""Freeze the pre-root-commit test issuances into an archival record.

  python scripts/freeze_vbuterin_2013_prerelease.py \\
      --check mempool-check.json --trace mempool-trace.json --label mempool.space \\
      --check blockstream-check.json --trace blockstream-trace.json --label blockstream.info \\
      --run-id <workflow run> > historical/census/vbuterin_2013_mainnet_prerelease.json

--check is the JSON printed by check_vbuterin_2013_prerelease.py and --trace
the JSON printed by trace_vbuterin_2013_prerelease.py, one pair per service.
Optionally --selection (one per service, same order) adds the coin-selection
replay of check_vbuterin_2013_prerelease_selection.py, with --selection-run-id.
The first service supplies every record; each genesis lists the services
whose check and trace agree with it. Nothing is recomputed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wallet_index(label: str | None) -> str | None:
    """'genpriv 10 0 (uncompressed)' -> 'key 10 (chain 0, uncompressed)'."""

    if not label:
        return None
    _, i, ch, form = label.split(" ", 3)
    return f"key {i} (chain {ch}, {form.strip('()')})"


def evidence(check_tx: dict) -> dict:
    chunk = check_tx.get("first_metadata_chunk") or {}
    return {
        "funding_inputs": [
            {"prev": i["prev"], "address": i["address"], "value_sats": i["value"],
             "test_js_wallet": wallet_index(i["test_js_wallet"])}
            for i in check_tx["inputs"]
        ],
        "outputs": [
            {"address": o["address"], "value_sats": o["value"], "test_js_wallet": wallet_index(o["test_js_wallet"])}
            for o in check_tx["outputs"]
        ],
        "unsigned_size_bytes": check_tx["unsigned_size"],
        "fee_sats": check_tx["fee"],
        "root_commit_fee_rule_sats": check_tx["root_commit_fee_rule"],
        "first_metadata_chunk_hex": chunk.get("hex"),
    }


# node-sx (vbuterin/node-sx) as committed before each transaction was mined
NODE_SX_AT_THE_TIME = {
    "eef2faa6540b37f5075458a9c435614cb043ac545af95add18cb76c083f0e03d": (
        "6d2a098 (2013-09-22 09:58 UTC)",
        "No send_to_outputs yet; transaction building is get_enough_utxo_from_history plus mktx.",
    ),
    "65d423d4eff6b5c737eed3b711f7c606e79d827b2a0d2936ffbd07ecfbac77d4": (
        "05f4f7d (2013-09-24 15:23 UTC, about 3 h before)",
        "send_to_outputs exists (added 85ffd48 that morning) but cannot run: it reads undefined h, cb3 and "
        "o.outputs. Read as intended it would set output 0 to 60000 and then add the excess to it, not the "
        "20000 the transaction pays.",
    ),
}


def coin_selection(sel: dict, txid: str) -> dict:
    t = next(x for x in sel["transactions"] if x["txid"] == txid)
    orders = list(t["orders"].values())
    for o in orders:  # the selection is a set; its listing order follows the replayed history order
        for c in o["candidate_amounts"].values():
            c["selected"] = sorted(c["selected"])
    if any(o != orders[0] for o in orders):
        raise SystemExit(f"{txid}: replay depends on history order")
    version, note = NODE_SX_AT_THE_TIME[txid]
    intervals = orders[0]["matching_amount_intervals"]
    return {
        "node_sx_at_the_time": version,
        "node_sx_note": note,
        "routine": "get_enough_utxo_from_history (identical from cb43ac2, 2013-09-17, to a7cc669, 2013-09-28)",
        "key0_unspent_before": [{"outpoint": o["outpoint"], "value_sats": o["value"], "block_height": o["height"]}
                                for o in t["unspent_before_block"]],
        "actual_inputs": t["actual_inputs"],
        "requests_reproducing_inputs": [{"from_sats": lo, "to_sats": hi} for lo, hi in intervals],
        "candidate_requests": {name: {"sats": c["amount"], "selects": c["selected"], "reproduces": c["matches"]}
                               for name, c in orders[0]["candidate_amounts"].items()},
        "reproduced": any(c["matches"] for c in orders[0]["candidate_amounts"].values()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", type=Path, action="append", required=True)
    ap.add_argument("--trace", type=Path, action="append", required=True)
    ap.add_argument("--label", action="append", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--selection", type=Path, action="append", default=[])
    ap.add_argument("--selection-run-id")
    args = ap.parse_args()
    if args.selection and (len(args.selection) != len(args.label) or not args.selection_run_id):
        ap.error("give one --selection per service and --selection-run-id")
    if not len(args.check) == len(args.trace) == len(args.label):
        ap.error("give one --check, --trace and --label per service")

    services = []
    for k, (check_path, trace_path, label) in enumerate(zip(args.check, args.trace, args.label)):
        check = json.loads(check_path.read_text(encoding="utf-8"))
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        services.append({
            "label": label,
            "check_sha256": sha256(check_path),
            "trace_sha256": sha256(trace_path),
            "check": {t["txid"]: t for t in check["transactions"] if t.get("pre_root")},
            "trace": {g["assessment"]["txid"]: g for g in trace["geneses"]},
            "wallet_sample": check["test_js_wallet"],
            "selection": json.loads(args.selection[k].read_text(encoding="utf-8")) if args.selection else None,
            "selection_sha256": sha256(args.selection[k]) if args.selection else None,
        })

    first = services[0]
    geneses = []
    for txid, g in first["trace"].items():
        a, lin = g["assessment"], g["lineage"]
        ev = evidence(first["check"][txid])
        sel = coin_selection(first["selection"], txid) if first["selection"] else None
        confirmed = [s["label"] for s in services
                     if txid in s["trace"] and s["trace"][txid] == g
                     and txid in s["check"] and evidence(s["check"][txid]) == ev
                     and (sel is None or coin_selection(s["selection"], txid) == sel)]
        geneses.append({
            "txid": txid,
            "block_height": a["block_height"],
            "block_time": a["block_time"],
            "colored_vouts": a["colored_vouts"],
            "marker_index": a["marker_index"],
            "fee_sats": a["fee_sats"],
            "metadata_hex": a["metadata_hex"],
            "census_checks": a["checks"],
            "issued_sats": lin["issued_sats"],
            "held_sats": lin["held_sats"],
            "burned_to_fees_sats": lin["burned_to_fees_sats"],
            "transactions_visited": lin["transactions_visited"],
            "truncated": lin["truncated"],
            "holdings": lin["holdings"],
            "fee_losses": lin["fee_losses"],
            "evidence": ev,
            **({"coin_selection": sel} if sel else {}),
            "confirmed_by": confirmed,
        })
    geneses.sort(key=lambda g: (g["block_height"], g["txid"]))
    holdings = [h for g in geneses for h in g["holdings"]]

    record = {
        "census_id": "vbuterin-coloredcoins-2013-mainnet-prerelease-v0.1",
        "network": "bitcoin-mainnet",
        "relation_to_census": (
            "Not part of vbuterin-coloredcoins-2013-mainnet-v0.1, which rejects both transactions as confirmed "
            "before the root commit (aa2bc9f, 2013-09-27 22:09:50 UTC). Recorded separately as Vitalik Buterin's "
            "own test issuances made while developing the same project."
        ),
        "attribution": (
            "Both transactions are funded by key 0 of the wallet test.js derives from its hard-coded seed "
            f"({first['wallet_sample']['seed']}, root commit aa2bc9f) via node-sx genpriv (Electrum 1.x "
            "derivation), and pay their colored outputs to keys 1, 2 and 10 of that wallet."
        ),
        "differences_from_root_commit": [
            "No change output: every sat not assigned to an output went to the miner (fees 40000 and 50000), "
            "where root-commit mkgenesis with node-sx a7cc669 charges 10000 per started KB of the unsigned "
            "transaction (10000 for both) and adds the change to output 0.",
            "eef2faa6: the first metadata chunk is 20 non-text bytes (dd359ad6...502f) before the text; it is not a "
            "test.js wallet key (first 200 keys, both chains) or a plain hash of the text. Root-commit mkgenesis "
            "only cuts chunks from the metadata string.",
        ] + ([
            "Coin selection (node-sx as committed at the time, replayed against the history of test.js key 0): "
            "eef2faa6 is reproduced, since get_enough_utxo_from_history picks exactly its two 50000 inputs for "
            "any request from 50001 to 100000 sats. 65d423d4 is not: key 0 also held an 80000-sat coin, which "
            "the routine picks for any request up to 80000; it spends the 100000-sat coin only for requests of "
            "80001-100000, more than the transaction's outputs plus a 10000 fee (60000). Its builder chose the "
            "input some other way.",
        ] if args.selection else []),
        "caveats": [
            "The test.js seed is public in the archived source, so anyone can derive these keys and spend these "
            "outputs; later holders say nothing about who controls them.",
        ],
        "method": (
            "Colored outputs are the outputs before the marker, as in every revision; holders are traced with the "
            "census tracer (vertical flow, 0-based half-open satoshi ranges) and cross-checked backwards with "
            "find_genesis. Evidence: scripts/check_vbuterin_2013_prerelease.py; tracing: "
            "scripts/trace_vbuterin_2013_prerelease.py; coin selection: "
            "scripts/check_vbuterin_2013_prerelease_selection.py."
        ),
        "sources": [
            {"service": s["label"], "workflow_run": args.run_id, "check_sha256": s["check_sha256"],
             "trace_sha256": s["trace_sha256"],
             **({"selection_workflow_run": args.selection_run_id, "selection_sha256": s["selection_sha256"]}
                if s["selection"] else {})}
            for s in services
        ],
        "summary": {
            "geneses": len(geneses),
            "issued_sats": sum(g["issued_sats"] for g in geneses),
            "held_sats": sum(g["held_sats"] for g in geneses),
            "burned_to_fees_sats": sum(g["burned_to_fees_sats"] for g in geneses),
            "holdings": len(holdings),
            "holdings_verified_by_find_genesis": sum(1 for h in holdings if h["find_genesis_verified"]),
            "geneses_confirmed_by_all_services": sum(1 for g in geneses if len(g["confirmed_by"]) == len(services)),
        },
        "geneses": geneses,
    }
    print(json.dumps(record, indent=1, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
