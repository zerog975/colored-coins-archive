#!/usr/bin/env python3
"""Print a compact, human-readable summary of a census_vbuterin_2013.py result.

Used by the census workflow so results can be read from the job log.

  python scripts/summarize_vbuterin_2013_census.py results/mempool-mainnet.json
"""

from __future__ import annotations

import collections
import json
import sys


def main(path: str) -> int:
    data = json.load(open(path, encoding="utf-8"))
    print(f"status={data.get('status')} error={data.get('error')}")
    disc = data.get("discovery") or {}
    print("discovery:", json.dumps({k: v for k, v in disc.items() if k != "lookup_errors"}))
    for err in (disc.get("lookup_errors") or [])[:20]:
        print("  lookup_error:", err["txid"], err["error"])

    candidates = data.get("candidates", [])
    consistent = [c for c in candidates if c["matching_rulesets"]]
    rejected = [c for c in candidates if not c["matching_rulesets"]]
    print(f"candidates={len(candidates)} consistent={len(consistent)} rejected={len(rejected)}")

    reasons = collections.Counter()
    for c in rejected:
        for rs in c["checks"].values():
            for r in rs:
                reasons[r.split(" ")[0] + " " + " ".join(r.split(" ")[2:5]) if r.startswith("output") else r[:60]] += 1
    print("top rejection reasons:", reasons.most_common(8))
    print("rulesets:", collections.Counter(tuple(c["matching_rulesets"]) for c in consistent).most_common())
    print("ruleset by date:", collections.Counter(c["ruleset_by_date"] for c in consistent).most_common())
    print("colored outputs per genesis:", sorted(collections.Counter(len(c["colored_vouts"]) for c in consistent).items()))
    print("fees:", collections.Counter(c["fee_sats"] for c in consistent).most_common(6))
    texts = collections.Counter()
    for c in consistent:
        for t in c["metadata_text"].values():
            texts[repr(t)[:70]] += 1
    print(f"distinct metadata texts={len(texts)}; most common:")
    for t, n in texts.most_common(40):
        print(f"  {n:4d}  {t}")

    lineages = {l["genesis_txid"]: l for l in data.get("lineages", [])}
    verified = collections.Counter()
    for l in lineages.values():
        for h in l.get("holdings", []):
            verified[str(h.get("find_genesis_verified"))] += 1
    print("holder find_genesis verification:", dict(verified))
    print("lineage errors/truncated:", sum(1 for l in lineages.values() if l.get("error") or l.get("truncated")))
    print("summary:", json.dumps(data.get("summary")))

    print("\nheight   genesis txid                                                      rs  col  issued    held  burned hold vis  metadata")
    for c in consistent:
        l = lineages.get(c["txid"], {})
        rs = "+".join("R" if r.endswith("09-27") else "F" for r in c["matching_rulesets"])
        text = next(iter(c["metadata_text"].values()), None)
        print(f"{c['block_height']} {c['txid']} {rs:>3} {len(c['colored_vouts']):>4} "
              f"{l.get('issued_sats', 0):>7} {l.get('held_sats', 0):>7} {l.get('burned_to_fees_sats', 0):>7} "
              f"{len(l.get('holdings', [])):>4} {l.get('transactions_visited', 0):>3}  {repr(text)[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
