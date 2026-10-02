#!/usr/bin/env python3
"""Find and trace every coin issued with the 2013 vbuterin/coloredcoins tool.

1. Discovery: page through the confirmed transactions of the marker address
   (1111111111111111111114oLvT2 on mainnet; the same all-zero hash160 is
   mfWxJ45yp2SFn7UciZyNpvDKrzbhyfKrY8 on testnet), newest first, back to the
   root commit date,
   or read candidate TXIDs from a file (for example the output of Bitcoin
   Core ``scantxoutset start '["raw(76a914<40 zeros>88ac)"]'``).
2. Assessment: compare each candidate with the historical genesis layouts.
3. Census: follow the colored satoshis of every consistent candidate forward
   to current unspent holders, cross-checking each holder with find_genesis.

Examples:

  python scripts/census_vbuterin_2013.py --base-url https://mempool.space --network mainnet
  python scripts/census_vbuterin_2013.py --base-url https://blockstream.info/testnet --network testnet3
  python scripts/census_vbuterin_2013.py --base-url https://mempool.space \\
      --network mainnet --candidates-file scantxoutset.json

GET requests only. No wallet or broadcast capability.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from indexer.protocols import vbuterin_2013 as vb
from indexer.sources.esplora import EsploraError, EsploraSource
from indexer.vbuterin_2013_census import (
    ROOT_COMMIT_TIME,
    CandidateAssessment,
    LineageResult,
    Vbuterin2013Census,
    assess_genesis_candidate,
    metadata_text,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="Esplora-compatible base URL")
    parser.add_argument("--network", required=True, help="Evidence label, e.g. mainnet or testnet3")
    parser.add_argument("--start-time", type=int, default=ROOT_COMMIT_TIME,
                        help="Earliest block time (default: root commit, 2013-09-27T22:09:50Z)")
    parser.add_argument("--end-time", type=int, default=1420070400,
                        help="Latest block time to assess (default: 2015-01-01T00:00:00Z)")
    parser.add_argument("--max-pages", type=int, default=20000,
                        help="Address pages to read (25 transactions each) before stopping")
    parser.add_argument("--max-transactions", type=int, default=5000,
                        help="Spending transactions to follow per genesis before stopping")
    parser.add_argument("--candidates-file", type=Path,
                        help="JSON list of TXIDs, or scantxoutset output, instead of address paging")
    parser.add_argument("--marker-address",
                        help="Marker address to page (default: version-0 form, or version-111 when --network contains 'test')")
    parser.add_argument("--no-verify", action="store_true", help="Skip find_genesis cross-checks")
    parser.add_argument("--request-delay", type=float, default=1.0,
                        help="Minimum seconds between HTTP requests (default 1.0); 429s are retried with backoff")
    parser.add_argument("--start-after", help="Resume address paging after this TXID (the resume_after of a previous run)")
    return parser


def _marker_paying(vout_data: list[dict]) -> bool:
    return any(vb.is_marker_script(str(v.get("scriptpubkey", ""))) for v in vout_data)


def discover_by_address(source: EsploraSource, args) -> tuple[list[CandidateAssessment], dict]:
    stats = {"method": "address-paging", "pages_read": 0, "transactions_seen": 0,
             "marker_transactions_in_window": 0, "reached_start_time": False,
             "history_exhausted": False, "page_limit_hit": False}
    found: list[CandidateAssessment] = []
    last_seen = getattr(args, "start_after", None) or None
    stats["started_after"] = last_seen
    while True:
        if stats["pages_read"] >= args.max_pages:
            stats["page_limit_hit"] = True
            break
        try:
            page = source.address_chain_txs_page(args.marker_address, last_seen)
        except EsploraError as exc:
            if stats["pages_read"] == 0 and not last_seen:
                raise
            stats["error"] = str(exc)  # keep what was found; resume from last_seen
            break
        stats["pages_read"] += 1
        if stats["pages_read"] % 50 == 0:
            oldest = (page[-1].get("status") or {}).get("block_time") if page else None
            print(f"pages={stats['pages_read']} seen={stats['transactions_seen']} oldest_block_time={oldest} last_seen={last_seen}",
                  file=sys.stderr, flush=True)
        if not page:
            if stats["pages_read"] == 1:
                # The marker address has a long history on mainnet; an empty
                # first page means the query failed, not that nothing exists.
                raise EsploraError(f"explorer returned no transactions for {args.marker_address}; unverified, not evidence of absence")
            stats["history_exhausted"] = True
            break
        for raw in page:
            stats["transactions_seen"] += 1
            status = raw.get("status") or {}
            block_time = status.get("block_time")
            if block_time is None or not (args.start_time <= block_time <= args.end_time):
                continue
            vout = raw.get("vout", [])
            if not _marker_paying(vout):
                continue
            stats["marker_transactions_in_window"] += 1
            vin = raw.get("vin", [])
            input_values = None
            if vin and not vin[0].get("is_coinbase") and all(v.get("prevout") for v in vin):
                input_values = [int(v["prevout"]["value"]) for v in vin]
            found.append(assess_genesis_candidate(
                str(raw["txid"]),
                [int(v["value"]) for v in vout],
                [str(v.get("scriptpubkey", "")) for v in vout],
                input_values=input_values,
                block_height=status.get("block_height"),
                block_time=block_time,
            ))
        oldest = (page[-1].get("status") or {}).get("block_time")
        if oldest is not None and oldest < args.start_time:
            stats["reached_start_time"] = True
            break
        last_seen = str(page[-1]["txid"])
    stats["resume_after"] = None if stats["reached_start_time"] or stats["history_exhausted"] else last_seen
    found.sort(key=lambda a: (a.block_height or 0, a.txid))
    return found, stats


def load_candidate_txids(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "unspents" in data:  # bitcoin-cli scantxoutset
        return sorted({u["txid"] for u in data["unspents"]})
    return sorted({str(t) for t in data})


def discover_from_file(source: EsploraSource, args) -> tuple[list[CandidateAssessment], dict]:
    txids = load_candidate_txids(args.candidates_file)
    found = []
    lookup_errors: list[dict] = []
    missing: list[str] = []
    for txid in txids:
        try:
            tx = source.get_transaction(txid)
            if tx is None:
                missing.append(txid)
                continue
            input_values = None
            if not tx.is_coinbase:
                parents = [source.get_transaction(i.prev_txid) for i in tx.inputs]
                if all(parents):
                    input_values = [p.outputs[i.prev_vout].value_sats for p, i in zip(parents, tx.inputs)]
        except EsploraError as exc:
            lookup_errors.append({"txid": txid, "error": str(exc)})  # unassessed, not rejected
            continue
        found.append(assess_genesis_candidate(
            txid,
            [o.value_sats for o in tx.outputs],
            [o.script_pubkey_hex for o in tx.outputs],
            input_values=input_values,
            block_height=tx.block_height,
            block_time=tx.block_time,
        ))
    found.sort(key=lambda a: (a.block_height or 0, a.txid))
    stats = {"method": "candidates-file", "file": str(args.candidates_file), "txids": len(txids),
             "assessed": len(found), "missing": missing, "lookup_errors": lookup_errors}
    if lookup_errors:
        stats["error"] = f"{len(lookup_errors)} candidate(s) could not be fetched; see lookup_errors"
    return found, stats


def assessment_json(a: CandidateAssessment) -> dict:
    return {
        "txid": a.txid,
        "block_height": a.block_height,
        "block_time": a.block_time,
        "marker_index": a.marker_index,
        "first_marker_index": a.first_marker_index,
        "colored_vouts": list(a.colored_vouts),
        "fee_sats": a.fee_sats,
        "ruleset_by_date": a.ruleset_by_date,
        "matching_rulesets": list(a.matching_rulesets),
        "checks": {c.ruleset: list(c.reasons) for c in a.checks},
        "metadata_hex": a.metadata_hex,
        "metadata_error": a.metadata_error,
        "metadata_text": {r: metadata_text(a.metadata_hex, r) for r in a.matching_rulesets},
    }


def lineage_json(r: LineageResult) -> dict:
    return {
        "genesis_txid": r.genesis_txid,
        "issued_sats": r.issued_sats,
        "held_sats": r.held_sats,
        "burned_to_fees_sats": r.burned_sats,
        "transactions_visited": r.transactions_visited,
        "truncated": r.truncated,
        "missing_transactions": sorted(set(r.missing)),
        "holdings": [
            {
                "txid": h.txid, "vout": h.vout, "address": h.address, "value_sats": h.value_sats,
                "colored_sats": h.colored_sats, "block_height": h.block_height,
                "find_genesis_verified": h.verified,
                "segments": [
                    {"start": s.start, "end": s.end, "genesis_vout": s.genesis_vout,
                     "genesis_offset": s.genesis_offset}
                    for s in h.segments
                ],
            }
            for h in r.holdings
        ],
        "fee_losses": [
            {"txid": f.txid, "sats": f.segment.size, "genesis_vout": f.segment.genesis_vout}
            for f in r.fee_losses
        ],
    }


def main() -> int:
    args = build_parser().parse_args()
    if not args.marker_address:
        version = 0x6F if "test" in args.network.lower() else 0x00
        args.marker_address = vb.base58check_encode(vb.MARKER_HASH160, version)
    source = EsploraSource(args.base_url, network_label=args.network, request_delay=args.request_delay)
    payload: dict = {"network": args.network, "base_url": args.base_url,
                     "marker_address": args.marker_address,
                     "window": {"start_time": args.start_time, "end_time": args.end_time}}
    try:
        if args.candidates_file:
            candidates, stats = discover_from_file(source, args)
        else:
            candidates, stats = discover_by_address(source, args)
        payload["discovery"] = stats
        payload["candidates"] = [assessment_json(a) for a in candidates]
        census = Vbuterin2013Census(source, max_transactions=args.max_transactions,
                                    verify=not args.no_verify)
        payload["lineages"] = []
        for a in candidates:
            if not a.consistent:
                continue
            try:
                payload["lineages"].append(lineage_json(census.trace(a.txid, a.colored_vouts)))
            except EsploraError as exc:
                payload["lineages"].append({"genesis_txid": a.txid, "error": str(exc), "truncated": True,
                                            "issued_sats": 0, "held_sats": 0, "burned_to_fees_sats": 0})
    except EsploraError as exc:
        payload["status"] = "lookup-error"
        payload["error"] = str(exc)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2

    consistent = [c for c in payload["candidates"] if c["matching_rulesets"]]
    incomplete = (stats.get("page_limit_hit") or stats.get("error") or stats.get("started_after")
                  or any(l["truncated"] for l in payload["lineages"]))
    payload["summary"] = {
        "marker_transactions_assessed": len(payload["candidates"]),
        "consistent_geneses": len(consistent),
        "issued_sats": sum(l["issued_sats"] for l in payload["lineages"]),
        "held_sats": sum(l["held_sats"] for l in payload["lineages"]),
        "burned_to_fees_sats": sum(l["burned_to_fees_sats"] for l in payload["lineages"]),
    }
    payload["status"] = "incomplete" if incomplete else "complete"
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
