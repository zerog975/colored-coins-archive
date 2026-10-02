#!/usr/bin/env python3
"""Freeze two independent census_vbuterin_2013.py results into one archival record.

  python scripts/freeze_vbuterin_2013_census.py \\
      --primary mempool-mainnet.json --primary-label mempool.space \\
      --secondary blockstream-mainnet.json --secondary-label blockstream.info \\
      --run-id 36930765700 --input historical/census/inputs/vbuterin_2013_mainnet_scantxoutset.json \\
      > historical/census/vbuterin_2013_mainnet_v0.1.json

The primary result supplies every record; each genesis is marked with the
services that produced an identical assessment and lineage. Nothing is
recomputed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lineage_key(lineage: dict) -> tuple:
    return (
        lineage["issued_sats"], lineage["held_sats"], lineage["burned_to_fees_sats"],
        sorted((h["txid"], h["vout"], h["colored_sats"], json.dumps(h["segments"], sort_keys=True))
               for h in lineage.get("holdings", [])),
        sorted((f["txid"], f["sats"]) for f in lineage.get("fee_losses", [])),
    )


def assessment_key(candidate: dict) -> tuple:
    return (candidate["matching_rulesets"], candidate["checks"], candidate["metadata_hex"],
            candidate["fee_sats"], candidate["block_height"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", type=Path, required=True)
    ap.add_argument("--primary-label", required=True)
    ap.add_argument("--secondary", type=Path, required=True)
    ap.add_argument("--secondary-label", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--input", type=Path, required=True)
    args = ap.parse_args()

    P = json.loads(args.primary.read_text(encoding="utf-8"))
    S = json.loads(args.secondary.read_text(encoding="utf-8"))
    sc = {c["txid"]: c for c in S["candidates"]}
    sl = {l["genesis_txid"]: l for l in S["lineages"] if not l.get("error")}
    pl = {l["genesis_txid"]: l for l in P["lineages"]}

    geneses, rejected = [], []
    agree_assess = disagree_assess = 0
    for c in P["candidates"]:
        other = sc.get(c["txid"])
        if other is not None:
            if assessment_key(other) == assessment_key(c):
                agree_assess += 1
            else:
                disagree_assess += 1
        if not c["matching_rulesets"]:
            first = next((r for rs in c["checks"].values() for r in rs), "")
            rejected.append({"txid": c["txid"], "block_height": c["block_height"], "reason": first})
            continue
        lin = pl[c["txid"]]
        confirmed = [args.primary_label]
        if other is not None and assessment_key(other) == assessment_key(c) \
                and c["txid"] in sl and lineage_key(sl[c["txid"]]) == lineage_key(lin):
            confirmed.append(args.secondary_label)
        flags = []
        if not c["metadata_hex"]:
            flags.append("no metadata: a plain 2-output payment to the marker matches the 2013-09-27 layout; unconfirmed")
        geneses.append({
            "txid": c["txid"],
            "block_height": c["block_height"],
            "block_time": c["block_time"],
            "matching_rulesets": c["matching_rulesets"],
            "ruleset_by_date": c["ruleset_by_date"],
            "colored_vouts": c["colored_vouts"],
            "marker_index": c["marker_index"],
            "fee_sats": c["fee_sats"],
            "metadata_hex": c["metadata_hex"],
            "metadata_text": c["metadata_text"],
            "issued_sats": lin["issued_sats"],
            "held_sats": lin["held_sats"],
            "burned_to_fees_sats": lin["burned_to_fees_sats"],
            "transactions_visited": lin["transactions_visited"],
            "holdings": lin["holdings"],
            "fee_losses": lin["fee_losses"],
            "confirmed_by": confirmed,
            "flags": flags,
        })
    geneses.sort(key=lambda g: (g["block_height"], g["txid"]))

    holdings = [h for g in geneses for h in g["holdings"]]
    record = {
        "census_id": "vbuterin-coloredcoins-2013-mainnet-v0.1",
        "rulesets": ["vbuterin-coloredcoins-2013-09-27", "vbuterin-coloredcoins-2013-10-01"],
        "network": "bitcoin-mainnet",
        "kernel": "indexer/protocols/vbuterin_2013.py",
        "census_code": "indexer/vbuterin_2013_census.py, scripts/census_vbuterin_2013.py",
        "candidate_input": {"path": str(args.input), "sha256": sha256(args.input)},
        "sources": [
            {"service": args.primary_label, "workflow_run": args.run_id, "result_sha256": sha256(args.primary),
             "status": P["status"]},
            {"service": args.secondary_label, "workflow_run": args.run_id, "result_sha256": sha256(args.secondary),
             "status": S["status"], "lookup_errors": S["discovery"].get("lookup_errors", []),
             "lineage_errors": [l["genesis_txid"] for l in S["lineages"] if l.get("error")]},
        ],
        "method": (
            "Candidates: every unspent output paying the marker script 76a914<20 zero bytes>88ac between heights "
            "258000 and 340000 (Bitcoin Core scantxoutset; marker outputs are unspendable, so the UTXO set holds all "
            "of them). Each candidate is assessed against both historical genesis layouts; consistent geneses are "
            "traced forward as satoshi ranges (0-based, half-open) and every holder is cross-checked backwards with "
            "find_genesis. Interpretation and deviations: docs/reconstruction/VBUTERIN_2013_KERNEL.md, "
            "docs/COMPATIBILITY.md."
        ),
        "summary": {
            "candidates_assessed": len(P["candidates"]),
            "consistent_geneses": len(geneses),
            "rejected": len(rejected),
            "issued_sats": sum(g["issued_sats"] for g in geneses),
            "held_sats": sum(g["held_sats"] for g in geneses),
            "burned_to_fees_sats": sum(g["burned_to_fees_sats"] for g in geneses),
            "holdings": len(holdings),
            "holdings_verified_by_find_genesis": sum(1 for h in holdings if h["find_genesis_verified"]),
            "geneses_confirmed_by_both_services": sum(1 for g in geneses if len(g["confirmed_by"]) == 2),
            "geneses_single_source": [g["txid"] for g in geneses if len(g["confirmed_by"]) == 1],
            "assessments_compared": agree_assess + disagree_assess,
            "assessment_disagreements": disagree_assess,
            "flagged": [g["txid"] for g in geneses if g["flags"]],
            "first_genesis": {k: geneses[0][k] for k in ("txid", "block_height", "block_time")},
            "last_genesis": {k: geneses[-1][k] for k in ("txid", "block_height", "block_time")},
        },
        "geneses": geneses,
        "rejected": rejected,
    }
    print(json.dumps(record, indent=1, sort_keys=False, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
