#!/usr/bin/env python3
"""Check the two pre-root-commit marker transactions against the root-commit code.

  python scripts/check_vbuterin_2013_prerelease.py --base-url https://mempool.space

Read-only. For each transaction it reports:

* the size of the unsigned transaction that ``sx mktx`` would have built and
  the fee node-sx ``send_to_outputs`` charges for it
  (10000 sats per started 1024 bytes, ``fee_multiplier = ceil(len(hex)/2048)``);
* the funding inputs, and whether any input address, output address or the
  first metadata chunk belongs to the wallet test.js derives from its
  hard-coded seed (``sx genpriv i 0``, Electrum v1 derivation);
* simple hash candidates for the 20-byte first metadata chunk.

The earliest census geneses are fetched too, so their funding addresses can be
compared with the pre-root ones.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from indexer.protocols.vbuterin_2013 import base58check_encode, hash160  # noqa: E402
from indexer.sources.esplora import EsploraSource  # noqa: E402

PRE_ROOT = [
    "eef2faa6540b37f5075458a9c435614cb043ac545af95add18cb76c083f0e03d",
    "65d423d4eff6b5c737eed3b711f7c606e79d827b2a0d2936ffbd07ecfbac77d4",
]
TEST_JS_SEED = "c356f24f29a795b51a03dc2e30304db0"  # test.js, root commit aa2bc9f
MARKER = "1111111111111111111114oLvT2"
CENSUS = Path(__file__).resolve().parents[1] / "historical" / "census" / "vbuterin_2013_mainnet_v0.1.json"

# secp256k1
P = 2**256 - 2**32 - 977
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0] and (a[1] + b[1]) % P == 0:
        return None
    if a == b:
        lam = 3 * a[0] * a[0] * pow(2 * a[1], -1, P) % P
    else:
        lam = (b[1] - a[1]) * pow(b[0] - a[0], -1, P) % P
    x = (lam * lam - a[0] - b[0]) % P
    return x, (lam * (a[0] - x) - a[1]) % P


def point(k: int):
    r, q = None, G
    while k:
        if k & 1:
            r = _add(r, q)
        q = _add(q, q)
        k >>= 1
    return r


def pubkeys(k: int) -> dict[str, bytes]:
    x, y = point(k)
    xb, yb = x.to_bytes(32, "big"), y.to_bytes(32, "big")
    return {"uncompressed": b"\x04" + xb + yb, "compressed": bytes([2 + (y & 1)]) + xb}


def electrum_v1_keys(seed: str, count: int, for_change: int) -> list[int]:
    """libwallet deterministic_wallet / Electrum 1.x, as used by ``sx genpriv``."""

    s = seed.encode()
    x = s
    for _ in range(100000):
        x = hashlib.sha256(x + s).digest()
    secexp = int.from_bytes(x, "big") % N
    mx, my = point(secexp)
    mpk = mx.to_bytes(32, "big") + my.to_bytes(32, "big")
    out = []
    for n in range(count):
        seq = hashlib.sha256(hashlib.sha256(f"{n}:{for_change}:".encode() + mpk).digest()).digest()
        out.append((secexp + int.from_bytes(seq, "big")) % N)
    return out


def varint_len(n: int) -> int:
    return 1 if n < 0xFD else 3 if n <= 0xFFFF else 5


def unsigned_size(tx: dict) -> int:
    """Bytes of the transaction with empty input scripts, as ``sx mktx`` emits it."""

    size = 4 + varint_len(len(tx["vin"])) + 41 * len(tx["vin"]) + varint_len(len(tx["vout"])) + 4
    for o in tx["vout"]:
        n = len(o["scriptpubkey"]) // 2
        size += 8 + varint_len(n) + n
    return size


def scriptsig_pubkey(hexstr: str) -> bytes | None:
    b = bytes.fromhex(hexstr)
    if not b:
        return None
    sig_len = b[0]
    rest = b[1 + sig_len:]
    if rest and rest[0] in (33, 65) and len(rest) == 1 + rest[0]:
        return rest[1:]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--wallet-size", type=int, default=200)
    ap.add_argument("--census-geneses", type=int, default=15)
    ap.add_argument("--request-delay", type=float, default=1.0)
    args = ap.parse_args()

    src = EsploraSource(args.base_url, network_label="bitcoin-mainnet", request_delay=args.request_delay)

    wallet: dict[str, str] = {}  # hash160 hex -> label
    for ch in (0, 1):
        for i, k in enumerate(electrum_v1_keys(TEST_JS_SEED, args.wallet_size, ch)):
            for form, pub in pubkeys(k).items():
                wallet[hash160(pub).hex()] = f"genpriv {i} {ch} ({form})"
    first = sorted(v for v in wallet.items() if v[1].startswith("genpriv 0 0") or v[1].startswith("genpriv 1 0"))
    report = {
        "service": args.base_url,
        "test_js_wallet": {
            "seed": TEST_JS_SEED,
            "keys_per_chain": args.wallet_size,
            "sample": {lbl: base58check_encode(bytes.fromhex(h), 0) for h, lbl in first},
        },
        "transactions": [],
    }

    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    txids = PRE_ROOT + [g["txid"] for g in census["geneses"][: args.census_geneses]]

    for txid in txids:
        tx = src._read(f"/api/tx/{txid}")
        if tx is None:
            report["transactions"].append({"txid": txid, "error": "not found"})
            continue
        usize = unsigned_size(tx)
        expected_fee = 10000 * -(-usize // 1024)
        ins = []
        for vin in tx["vin"]:
            pub = scriptsig_pubkey(vin.get("scriptsig", ""))
            h = hash160(pub).hex() if pub else None
            ins.append({
                "prev": f"{vin['txid']}:{vin['vout']}",
                "address": vin["prevout"].get("scriptpubkey_address"),
                "value": vin["prevout"]["value"],
                "test_js_wallet": wallet.get(h) if h else None,
                "pubkey_hash160": h,
            })
        outs, chunks, seen_marker = [], [], False
        for o in tx["vout"]:
            addr = o.get("scriptpubkey_address")
            spk = o["scriptpubkey"]
            h = spk[6:46] if spk.startswith("76a914") and spk.endswith("88ac") and len(spk) == 50 else None
            if seen_marker and h:
                chunks.append(h)
            if addr == MARKER and not seen_marker:
                seen_marker = True
            outs.append({"address": addr, "value": o["value"],
                         "test_js_wallet": wallet.get(h) if h else None})
        entry = {
            "txid": txid,
            "pre_root": txid in PRE_ROOT,
            "block_height": tx["status"].get("block_height"),
            "block_time": tx["status"].get("block_time"),
            "signed_size": tx["size"],
            "unsigned_size": usize,
            "fee": tx["fee"],
            "root_commit_fee_rule": expected_fee,
            "fee_matches_rule": tx["fee"] == expected_fee,
            "inputs": ins,
            "outputs": outs,
        }
        if txid in PRE_ROOT and chunks:
            c0 = chunks[0]
            text = b"".join(bytes.fromhex(c) for c in chunks[1:]).rstrip(b"\x00")
            cands = {}
            for name, data in (("text", text), ("text+nul", b"".join(bytes.fromhex(c) for c in chunks[1:]))):
                cands[f"hash160({name})"] = hash160(data).hex()
                cands[f"sha256({name})[:20]"] = hashlib.sha256(data).hexdigest()[:40]
                cands[f"sha1({name})"] = hashlib.sha1(data).hexdigest()
                cands[f"sha256d({name})[:20]"] = hashlib.sha256(hashlib.sha256(data).digest()).hexdigest()[:40]
            for i in ins:
                if i["pubkey_hash160"]:
                    cands[f"input pubkey hash160 {i['prev']}"] = i["pubkey_hash160"]
            entry["first_metadata_chunk"] = {
                "hex": c0,
                "test_js_wallet": wallet.get(c0),
                "as_address": base58check_encode(bytes.fromhex(c0), 0),
                "matches": [k for k, v in cands.items() if v == c0],
            }
        report["transactions"].append(entry)

    pre_funders = {i["address"] for t in report["transactions"] if t.get("pre_root") for i in t.get("inputs", [])}
    report["census_geneses_sharing_a_pre_root_funder"] = [
        t["txid"] for t in report["transactions"]
        if not t.get("pre_root") and pre_funders & {i["address"] for i in t.get("inputs", [])}
    ]
    report["any_test_js_wallet_hit"] = any(
        x.get("test_js_wallet") for t in report["transactions"] for x in t.get("inputs", []) + t.get("outputs", [])
    ) or any((t.get("first_metadata_chunk") or {}).get("test_js_wallet") for t in report["transactions"])
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
