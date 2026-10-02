#!/usr/bin/env python3
"""Trace the holders of the two pre-root-commit test issuances.

  python scripts/trace_vbuterin_2013_prerelease.py --base-url https://mempool.space

eef2faa6 and 65d423d4 were made from the test.js wallet before the root commit
(see scripts/check_vbuterin_2013_prerelease.py). The census rejects them on
date, so this traces them separately: colored outputs are the outputs before
the marker, and transfers follow the same vertical-flow rule as the census.
Read-only; prints JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from census_vbuterin_2013 import assessment_json, lineage_json  # noqa: E402
from check_vbuterin_2013_prerelease import PRE_ROOT  # noqa: E402
from indexer.sources.esplora import EsploraSource  # noqa: E402
from indexer.vbuterin_2013_census import Vbuterin2013Census, assess_genesis_candidate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--request-delay", type=float, default=1.0)
    args = ap.parse_args()

    source = EsploraSource(args.base_url, network_label="bitcoin-mainnet", request_delay=args.request_delay)
    census = Vbuterin2013Census(source)
    out = {"service": args.base_url, "geneses": []}
    for txid in PRE_ROOT:
        tx = source.get_transaction(txid)
        parents = [source.get_transaction(i.prev_txid) for i in tx.inputs]
        a = assess_genesis_candidate(
            txid,
            [o.value_sats for o in tx.outputs],
            [o.script_pubkey_hex for o in tx.outputs],
            input_values=[p.outputs[i.prev_vout].value_sats for p, i in zip(parents, tx.inputs)],
            block_height=tx.block_height,
            block_time=tx.block_time,
        )
        out["geneses"].append({"assessment": assessment_json(a),
                               "lineage": lineage_json(census.trace(txid, a.colored_vouts))})
    print("=====BEGIN prerelease-trace=====")
    print(json.dumps(out, sort_keys=True))
    print("=====END prerelease-trace=====")
    return 0 if not any(g["lineage"]["truncated"] for g in out["geneses"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
