#!/usr/bin/env python3
"""Look up the address of every holding in a frozen vbuterin 2013 census record.

  python scripts/address_vbuterin_2013_holdings.py --base-url https://mempool.space \\
      historical/census/vbuterin_2013_mainnet_v0.1.json

For each holding output it prints the output's address (as the census tracer
names holders) and whether the output has been spent since the census.
Read-only; prints JSON between BEGIN/END lines.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from indexer.sources.esplora import EsploraError, EsploraSource  # noqa: E402
from indexer.vbuterin_2013_census import output_address  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("record", type=Path)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--request-delay", type=float, default=1.0)
    args = ap.parse_args()

    record = json.loads(args.record.read_text(encoding="utf-8"))
    testnet = "test" in record["network"]
    source = EsploraSource(args.base_url, network_label=record["network"], request_delay=args.request_delay,
                           resolve_tx_index=False)
    out, errors = [], []
    for g in record["geneses"]:
        for h in g["holdings"]:
            try:
                tx = source.get_transaction(h["txid"])
                if tx is None:
                    raise EsploraError("transaction not found")
                o = tx.outputs[h["vout"]]
                if o.value_sats != h["value_sats"]:
                    raise EsploraError(f"value {o.value_sats} differs from the record")
                out.append({"genesis_txid": g["txid"], "txid": h["txid"], "vout": h["vout"],
                            "address": output_address(o.script_pubkey_hex, testnet=testnet),
                            "spent_by": source.get_spender(h["txid"], h["vout"])})
            except EsploraError as exc:
                errors.append({"txid": h["txid"], "vout": h["vout"], "error": str(exc)})
    print("=====BEGIN holder-addresses=====")
    print(json.dumps({"service": args.base_url, "holdings": out, "errors": errors}, sort_keys=True))
    print("=====END holder-addresses=====")
    print(f"{len(out)} holdings named, {len(errors)} errors", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
