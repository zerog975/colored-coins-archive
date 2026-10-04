#!/usr/bin/env python3
"""Replay node-sx coin selection for the two pre-root-commit test issuances.

  python scripts/check_vbuterin_2013_prerelease_selection.py --base-url https://mempool.space

node-sx ``get_enough_utxo_from_history`` (identical from cb43ac2, 2013-09-17,
through a7cc669, 2013-09-28) picks the smallest unspent output worth at least
``amount``; failing that it sorts all unspent outputs ascending and takes them
until the total reaches ``amount``. Its comparator returns a boolean, so the
replay reproduces V8 3.14's Array.prototype.sort (node 0.10): insertion sort
up to 10 elements, quicksort above, with true -> 1 and false -> 0.

For each transaction the unspent outputs of test.js key 0 are rebuilt from the
address history in chain order (height, then position in the block), i.e. as a
wallet that also saw its own unconfirmed transactions would have seen them
just before broadcasting it. The full key-0 history is printed too. The script
reports every amount for which the replay picks exactly the inputs the
transaction spent, under chronological and reverse-chronological history
order, and checks the amounts the candidate builders would request.
Read-only; prints JSON between BEGIN/END lines.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_vbuterin_2013_prerelease import PRE_ROOT  # noqa: E402
from indexer.sources.esplora import EsploraSource  # noqa: E402

KEY0 = "12LMM34ht4MqxeHgNjsPjZ3wdYcfWzHnBD"  # test.js genpriv 0 0


def _cmp(a: dict, b: dict) -> int:
    return 1 if a["value"] > b["value"] else 0  # `a.value > b.value` coerced by V8


def _insertion_sort(a: list, lo: int, hi: int) -> None:
    for i in range(lo + 1, hi):
        element = a[i]
        j = i - 1
        while j >= lo:
            tmp = a[j]
            if _cmp(tmp, element) > 0:
                a[j + 1] = tmp
            else:
                break
            j -= 1
        a[j + 1] = element


def _quick_sort(a: list, lo: int, hi: int) -> None:
    while True:
        if hi - lo <= 10:
            _insertion_sort(a, lo, hi)
            return
        third = lo + ((hi - lo) >> 1)
        v0, v1, v2 = a[lo], a[hi - 1], a[third]
        if _cmp(v0, v1) > 0:
            v0, v1 = v1, v0
        if _cmp(v0, v2) >= 0:
            v0, v1, v2 = v2, v0, v1
        elif _cmp(v1, v2) > 0:
            v1, v2 = v2, v1
        a[lo], a[hi - 1] = v0, v2
        pivot = v1
        low_end, high_start = lo + 1, hi - 1
        a[third] = a[low_end]
        a[low_end] = pivot
        i = low_end + 1
        while i < high_start:
            element = a[i]
            order = _cmp(element, pivot)
            if order < 0:
                a[i] = a[low_end]
                a[low_end] = element
                low_end += 1
            elif order > 0:
                stop = False
                while True:
                    high_start -= 1
                    if high_start == i:
                        stop = True
                        break
                    order = _cmp(a[high_start], pivot)
                    if not order > 0:
                        break
                if stop:
                    break
                a[i] = a[high_start]
                a[high_start] = element
                if order < 0:
                    element = a[i]
                    a[i] = a[low_end]
                    a[low_end] = element
                    low_end += 1
            i += 1
        if hi - high_start < low_end - lo:
            _quick_sort(a, high_start, hi)
            hi = low_end
        else:
            _quick_sort(a, lo, low_end)
            lo = high_start


def v8_sort(items: list) -> list:
    a = list(items)
    _quick_sort(a, 0, len(a))
    return a


def get_enough_utxo_from_history(utxo: list, amount: int) -> list | None:
    high = v8_sort([o for o in utxo if o["value"] >= amount])
    if high:
        return [high[0]]
    total = 0
    ordered = v8_sort(utxo)
    for i, o in enumerate(ordered):
        total += o["value"]
        if total >= amount:
            return ordered[: i + 1]
    return None


def matching_amounts(utxo: list, actual: set[str]) -> list[list[int]]:
    """Closed intervals of amounts whose selection is exactly ``actual``."""

    points = {1}
    for o in utxo:
        points |= {o["value"], o["value"] + 1}
    for order in (v8_sort(utxo),):
        total = 0
        for o in order:
            total += o["value"]
            points |= {total, total + 1}
    points = sorted(p for p in points if p >= 1)
    intervals: list[list[int]] = []
    for k, p in enumerate(points):
        sel = get_enough_utxo_from_history(utxo, p)
        hit = sel is not None and {o["outpoint"] for o in sel} == actual and len(sel) == len(actual)
        end = points[k + 1] - 1 if k + 1 < len(points) else None
        if hit:
            if intervals and intervals[-1][1] is not None and intervals[-1][1] + 1 == p:
                intervals[-1][1] = end
            else:
                intervals.append([p, end])
    return intervals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--request-delay", type=float, default=1.0)
    ap.add_argument("--max-pages", type=int, default=400)
    args = ap.parse_args()

    src = EsploraSource(args.base_url, network_label="bitcoin-mainnet", request_delay=args.request_delay)
    history, last = [], None
    for _ in range(args.max_pages):
        page = src.address_chain_txs_page(KEY0, last)
        if not page:
            break
        history += page
        last = page[-1]["txid"]
    else:
        raise SystemExit("address history longer than --max-pages")

    pos = {tx["txid"]: src.get_transaction(tx["txid"]).historical_sort_key()[:2] for tx in history}
    created, spent_at, listing = [], {}, []
    for tx in sorted(history, key=lambda t: pos[t["txid"]]):
        p = pos[tx["txid"]]
        ins = [(f"{i['txid']}:{i['vout']}", i["prevout"]["value"]) for i in tx["vin"]
               if (i.get("prevout") or {}).get("scriptpubkey_address") == KEY0]
        outs = [(f"{tx['txid']}:{n}", o["value"]) for n, o in enumerate(tx["vout"])
                if o.get("scriptpubkey_address") == KEY0]
        for op, v in outs:
            created.append({"outpoint": op, "value": v, "height": p[0], "pos": p})
        for op, _ in ins:
            spent_at[op] = p
        listing.append({"txid": tx["txid"], "block_height": p[0], "index_in_block": p[1],
                        "block_time": tx["status"].get("block_time"),
                        "spends_from_key0": ins, "pays_key0": outs,
                        "other_outputs": [(o.get("scriptpubkey_address"), o["value"]) for o in tx["vout"]
                                          if o.get("scriptpubkey_address") != KEY0]})

    report = {"service": args.base_url, "address": KEY0, "history_transactions": len(history),
              "history": listing, "transactions": []}
    for txid in PRE_ROOT:
        tx = src._read(f"/api/tx/{txid}")
        height = tx["status"]["block_height"]
        here = pos[txid]
        actual = {f"{i['txid']}:{i['vout']}" for i in tx["vin"]}
        before = [o for o in created if o["pos"] < here
                  and not (o["outpoint"] in spent_at and spent_at[o["outpoint"]] < here)]
        same_block = [o["outpoint"] for o in created if o["height"] == height]
        outputs = [o["value"] for o in tx["vout"]]
        n_out = len(outputs)
        candidates = {
            "outputs + 10000 (mktx, no change, 1 kB fee)": sum(outputs) + 10000,
            "outputs only": sum(outputs),
            "node-sx 05f4f7d send_to_outputs: 10000 + 10000 per output": 10000 + 10000 * n_out,
        }
        entry = {"txid": txid, "block_height": height, "actual_inputs": sorted(actual),
                 "outputs_total": sum(outputs), "output_count": n_out,
                 "unspent_before_block": [{k: o[k] for k in ("outpoint", "value", "height", "pos")} for o in before],
                 "created_in_same_block": same_block, "orders": {}}
        for label, utxo in (("chronological", sorted(before, key=lambda o: o["pos"])),
                            ("reverse-chronological",
                             sorted(before, key=lambda o: o["pos"], reverse=True))):
            entry["orders"][label] = {
                "matching_amount_intervals": matching_amounts(utxo, actual),
                "candidate_amounts": {
                    name: {"amount": amt,
                           "selected": [o["outpoint"] for o in (get_enough_utxo_from_history(utxo, amt) or [])],
                           "matches": {o["outpoint"] for o in (get_enough_utxo_from_history(utxo, amt) or [])}
                           == actual}
                    for name, amt in candidates.items()
                },
            }
        report["transactions"].append(entry)

    print("=====BEGIN prerelease-selection=====")
    print(json.dumps(report, sort_keys=True))
    print("=====END prerelease-selection=====")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
