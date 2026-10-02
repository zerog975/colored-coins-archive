#!/usr/bin/env python3
"""Render the frozen vbuterin 2013 census as a CSV and a Markdown table.

  python scripts/render_vbuterin_2013_census.py historical/census/vbuterin_2013_mainnet_v0.1.json

Writes <stem>.csv and <stem>.md next to the JSON. Both are derived views; the
JSON record is authoritative.
"""

from __future__ import annotations

import csv
import datetime
import io
import json
import sys
from pathlib import Path


COLUMNS = ["#", "block_height", "date_utc", "genesis_txid", "rules", "colored_outputs", "issued_sats",
           "held_sats", "burned_sats", "holders", "confirmed_by", "flags", "metadata"]


def rows(data: dict) -> list[list]:
    out = []
    for i, g in enumerate(data["geneses"], 1):
        rules = "+".join("Sep27" if r.endswith("09-27") else "Oct1" for r in g["matching_rulesets"])
        text = next(iter(g["metadata_text"].values()), None) or ""
        printable = "".join(c if 32 <= ord(c) < 127 else "." for c in text.rstrip("\x00"))
        date = datetime.datetime.fromtimestamp(g["block_time"], datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
        out.append([i, g["block_height"], date, g["txid"], rules, len(g["colored_vouts"]), g["issued_sats"],
                    g["held_sats"], g["burned_to_fees_sats"], len(g["holdings"]), " & ".join(g["confirmed_by"]),
                    "; ".join(g["flags"]), printable[:60]])
    return out


def render_csv(data: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    w.writerows(rows(data))
    return buf.getvalue()


def _code_cell(text: str) -> str:
    """Text for a Markdown table code span: only pipes need escaping there."""

    return text.replace("`", "'").replace("|", "\\|")


def render_md(data: dict, json_name: str) -> str:
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
        "| # | Block | Date (UTC) | Genesis transaction | Rules | Colored outputs | Issued | Held | Burned | Holders | Metadata |",
        "|---:|---:|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows(data):
        n, height, date, txid, rules, colored, issued, held, burned, holders, confirmed, flags, meta = r
        mark = ("" if " & " in confirmed else " ¹") + (" ⚠" if flags else "")
        link = f"[`{txid[:16]}…`](https://mempool.space/tx/{txid}){mark}"
        meta_cell = f"`{_code_cell(meta)}`" if meta else ""
        lines.append(f"| {n} | {height} | {date} | {link} | {rules} | {colored} | {issued:,} | {held:,} | "
                     f"{burned:,} | {holders} | {meta_cell} |")
    lines.append("")
    return "\n".join(lines)


def main(path: str) -> int:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    p.with_suffix(".csv").write_text(render_csv(data), encoding="utf-8")
    p.with_suffix(".md").write_text(render_md(data, p.name), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
