#!/usr/bin/env python3
"""Render the frozen vbuterin 2013 census as a CSV and a Markdown table.

  python scripts/render_vbuterin_2013_census.py historical/census/vbuterin_2013_mainnet_v0.1.json

Writes <stem>.csv and <stem>.md next to the JSON. When
vbuterin_2013_mainnet_prerelease.json sits beside it, its test issuances are
added as rows numbered P1, P2, ... and as a separate Markdown section. Both
views are derived; the JSON records are authoritative.
"""

from __future__ import annotations

import csv
import datetime
import io
import json
import sys
from pathlib import Path


PRERELEASE = "vbuterin_2013_mainnet_prerelease.json"
COLUMNS = ["#", "block_height", "date_utc", "genesis_txid", "rules", "colored_outputs", "issued_sats",
           "held_sats", "burned_sats", "holders", "confirmed_by", "flags", "metadata", "holder_addresses"]


def _printable(raw: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in raw.rstrip(b"\x00"))


def _addresses(genesis: dict) -> str:
    """Distinct holder addresses in holding order; empty when the record predates them."""

    seen = dict.fromkeys(h["address"] for h in genesis["holdings"] if h.get("address"))
    return " ".join(seen)


def rows(data: dict, prerelease: dict | None = None) -> list[list]:
    out = []
    for i, g in enumerate(data["geneses"], 1):
        rules = "+".join("Sep27" if r.endswith("09-27") else "Oct1" for r in g["matching_rulesets"])
        text = next(iter(g["metadata_text"].values()), None) or ""
        printable = _printable(text.encode("latin-1"))
        date = datetime.datetime.fromtimestamp(g["block_time"], datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
        out.append([i, g["block_height"], date, g["txid"], rules, len(g["colored_vouts"]), g["issued_sats"],
                    g["held_sats"], g["burned_to_fees_sats"], len(g["holdings"]), " & ".join(g["confirmed_by"]),
                    "; ".join(g["flags"]), printable[:60], _addresses(g)])
    for i, g in enumerate((prerelease or {}).get("geneses", []), 1):
        date = datetime.datetime.fromtimestamp(g["block_time"], datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
        out.append([f"P{i}", g["block_height"], date, g["txid"], "pre-release", len(g["colored_vouts"]),
                    g["issued_sats"], g["held_sats"], g["burned_to_fees_sats"], len(g["holdings"]),
                    " & ".join(g["confirmed_by"]), "made before the root commit with the test.js wallet",
                    _printable(bytes.fromhex(g["metadata_hex"] or ""))[:60], _addresses(g)])
    return out


def render_csv(data: dict, prerelease: dict | None = None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    w.writerows(rows(data, prerelease))
    return buf.getvalue()


def _code_cell(text: str) -> str:
    """Text for a Markdown table code span: only pipes need escaping there."""

    return text.replace("`", "'").replace("|", "\\|")


def _md_row(r: list) -> str:
    n, height, date, txid, rules, colored, issued, held, burned, holders, confirmed, flags, meta, _ = r
    mark = "" if str(n).startswith("P") else ("" if " & " in confirmed else " ¹") + (" ⚠" if flags else "")
    link = f"[`{txid[:16]}…`](https://mempool.space/tx/{txid}){mark}"
    meta_cell = f"`{_code_cell(meta)}`" if meta else ""
    return (f"| {n} | {height} | {date} | {link} | {rules} | {colored} | {issued:,} | {held:,} | "
            f"{burned:,} | {holders} | {meta_cell} |")


def _holder_table(geneses: list[dict], prefix: str) -> list[str]:
    out = ["| # | Holder address | Output | Colored sats | Since block | Moved since |",
           "|---:|---|---|---:|---:|---|"]
    for i, g in enumerate(geneses, 1):
        for h in g["holdings"]:
            addr = f"[`{h['address']}`](https://mempool.space/address/{h['address']})" if h.get("address") \
                else "(no address)"
            o = f"[`{h['txid'][:16]}…:{h['vout']}`](https://mempool.space/tx/{h['txid']}#vout={h['vout']})"
            moved = f"[`{h['spent_after_census'][:16]}…`](https://mempool.space/tx/{h['spent_after_census']})" \
                if h.get("spent_after_census") else ""
            out.append(f"| {prefix}{i} | {addr} | {o} | {h['colored_sats']:,} | {h['block_height']} | {moved} |")
    return out


HEADER = [
    "| # | Block | Date (UTC) | Genesis transaction | Rules | Colored outputs | Issued | Held | Burned | Holders | Metadata |",
    "|---:|---:|---|---|---|---:|---:|---:|---:|---:|---|",
]


def render_md(data: dict, json_name: str, prerelease: dict | None = None) -> str:
    s = data["summary"]
    lines = [
        f"# vbuterin/coloredcoins 2013 — mainnet issuances (census v0.1)",
        "",
        f"Generated from [`{json_name}`]({json_name}) by `scripts/render_vbuterin_2013_census.py`; the JSON is "
        "authoritative and also lists every holder and its satoshi ranges. Method, evidence and caveats: "
        "`docs/reconstruction/VBUTERIN_2013_KERNEL.md`.",
        "",
        f"- Issuances: **{s['consistent_geneses']}** "
        f"({s['geneses_confirmed_by_both_services']} confirmed identically by both explorers, "
        f"{len(s['geneses_single_source'])} single-source, marked ¹)",
        f"- Issued {s['issued_sats']:,} sats; still held {s['held_sats']:,} sats in {s['holdings']} holdings; "
        f"{s['burned_to_fees_sats']:,} sats paid to fees",
        "- Flagged unconfirmed: marked ⚠",
        "- Rules: *Sep27* = root commit layout (change in first colored output); *Oct1* = protocol-fix layout "
        "(separate change output)",
        "- Metadata: non-printable bytes shown as `.`, first 60 characters",
        "",
    ] + HEADER
    all_rows = rows(data, prerelease)
    lines += [_md_row(r) for r in all_rows if not str(r[0]).startswith("P")]
    if any("address" in h for g in data["geneses"] for h in g["holdings"]):
        ha = data["holder_addresses"]
        lines += [
            "",
            "## Holders",
            "",
            f"Every output holding colored sats at the census, by address ({ha['holdings_named']} holdings; "
            f"looked up on both explorers in workflow run {ha['workflow_run']}). *Moved since* links the "
            f"transaction that has spent the output since the census ({ha['holdings_spent_after_census']} so far); "
            "where the colored sats went from there is not traced here.",
            "",
        ] + _holder_table(data["geneses"], "")
    if prerelease:
        s = prerelease["summary"]
        lines += [
            "",
            "## Pre-release test issuances",
            "",
            f"Not counted above. From [`{PRERELEASE}`]({PRERELEASE}): {s['geneses']} marker transactions confirmed "
            "before the root commit, funded by and paid to the wallet test.js derives from its hard-coded seed, i.e. "
            "Vitalik Buterin's own tests of the same project. They follow the same layout (colored outputs, "
            "marker, metadata) but send all change to the miner, and the first carries a 20-byte binary metadata "
            f"prefix, so the root-commit code cannot rebuild them. Issued {s['issued_sats']:,} sats; still held "
            f"{s['held_sats']:,} sats in {s['holdings']} holdings; {s['burned_to_fees_sats']:,} sats paid to fees.",
            "",
        ] + HEADER + [_md_row(r) for r in all_rows if str(r[0]).startswith("P")]
        lines += [
            "",
            "Current holders (the address of each unspent output now carrying the colored sats):",
            "",
        ] + _holder_table(prerelease["geneses"], "P") + [
            "",
            "The test.js seed is public, so anyone can derive the keys of the original recipients; these "
            "holders are whoever spent the outputs, not necessarily anyone connected to the project.",
        ]
    lines.append("")
    return "\n".join(lines)


def main(path: str) -> int:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    pre_path = p.parent / PRERELEASE
    prerelease = json.loads(pre_path.read_text(encoding="utf-8")) if pre_path.exists() else None
    p.with_suffix(".csv").write_text(render_csv(data, prerelease), encoding="utf-8")
    p.with_suffix(".md").write_text(render_md(data, p.name, prerelease), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
