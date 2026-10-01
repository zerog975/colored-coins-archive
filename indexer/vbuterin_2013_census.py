"""Read-only census for the 2013 vbuterin/coloredcoins marker-address ruleset.

Two stages:

1. ``assess_genesis_candidate`` checks whether a transaction paying the marker
   address 1111111111111111111114oLvT2 has the output shape the historical
   ``mkgenesis`` produced, under either ruleset. That address is also a common
   burn address, so most payments to it are unrelated.

2. ``Vbuterin2013Census`` follows the colored satoshis of consistent
   candidates forward through spending transactions, as satoshi ranges, to
   their current unspent holders or to transaction fees.

The historical forward tracer (``find_current_owner``) cannot run and was not
reconstructed (docs/reconstruction/VBUTERIN_2013_KERNEL.md, defect 7). The
forward step here is the inverse of the reconstructed ``trace_to_parent``
(0-based offsets, half-open ranges); every holder is cross-checked backwards
with ``find_genesis``. Nothing here broadcasts or spends Bitcoin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from indexer.model import TransactionSource, TxRecord
from indexer.protocols import vbuterin_2013 as vb


# Author dates of the two ruleset-defining commits, as UTC Unix time.
ROOT_COMMIT_TIME = 1380319790  # aa2bc9f, 2013-09-27T22:09:50Z
PROTOCOL_FIX_COMMIT_TIME = 1380633235  # debeddc, 2013-10-01T13:13:55Z


@dataclass(frozen=True, slots=True)
class RulesetCheck:
    ruleset: str
    consistent: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    txid: str
    block_height: int | None
    block_time: int | None
    marker_index: int | None
    first_marker_index: int | None
    colored_vouts: tuple[int, ...]
    fee_sats: int | None
    ruleset_by_date: str | None
    checks: tuple[RulesetCheck, ...]
    metadata_hex: str | None
    metadata_error: str | None

    @property
    def matching_rulesets(self) -> tuple[str, ...]:
        return tuple(c.ruleset for c in self.checks if c.consistent)

    @property
    def consistent(self) -> bool:
        return bool(self.matching_rulesets)


def ruleset_by_date(block_time: int | None) -> str | None:
    """Ruleset of the newest source commit before the block time, if any.

    Only a hint: a user could run an older checkout, or patched code.
    """

    if block_time is None or block_time < ROOT_COMMIT_TIME:
        return None
    if block_time < PROTOCOL_FIX_COMMIT_TIME:
        return vb.RULESET_ROOT
    return vb.RULESET_PROTOCOL_FIX


def _check_ruleset(
    ruleset: str,
    values: Sequence[int],
    scripts: Sequence[str],
    marker: int,
    fee_sats: int | None,
) -> RulesetCheck:
    reasons: list[str] = []
    standard = vb.HISTORICAL_OUTPUT_VALUE
    last = len(values) - 1
    if ruleset == vb.RULESET_ROOT:
        excess_index = 0
    else:
        excess_index = last
        if marker >= last:
            reasons.append("no change output after the marker")
    for vout, value in enumerate(values):
        if vout != excess_index and value != standard:
            reasons.append(f"output {vout} is {value} sats, builder used {standard}")
    if values[excess_index] < 0:
        reasons.append("negative excess output")
    for vout in range(marker):
        if vb.historical_address_hash(scripts[vout]) is None:
            reasons.append(f"colored output {vout} has no historical address")
    if ruleset == vb.RULESET_PROTOCOL_FIX and marker < last:
        if vb.historical_address_hash(scripts[last]) is None:
            reasons.append("change output has no historical address")
    if fee_sats is not None and (fee_sats <= 0 or fee_sats % standard):
        reasons.append(f"fee {fee_sats} sats is not a positive multiple of {standard}")
    return RulesetCheck(ruleset, not reasons, tuple(reasons))


def assess_genesis_candidate(
    txid: str,
    output_values: Sequence[int],
    output_scripts: Sequence[str],
    *,
    input_values: Sequence[int] | None = None,
    block_height: int | None = None,
    block_time: int | None = None,
) -> CandidateAssessment:
    """Compare one marker-paying transaction against both historical layouts."""

    marker = vb.genesis_marker_index(output_scripts)
    first_marker = next(
        (i for i, s in enumerate(output_scripts) if vb.is_marker_script(s)), None
    )
    fee = None if input_values is None else sum(input_values) - sum(output_values)
    metadata_hex = metadata_error = None
    try:
        raw = vb.get_metadata_as_historical(output_scripts)
        metadata_hex = None if raw is None else raw.hex()
    except ValueError as exc:
        metadata_error = str(exc)

    checks: list[RulesetCheck] = []
    if marker is None or marker == 0:
        reason = "no marker output" if marker is None else "marker is output 0, so nothing is colored"
        checks = [RulesetCheck(r, False, (reason,)) for r in (vb.RULESET_ROOT, vb.RULESET_PROTOCOL_FIX)]
    else:
        for ruleset in (vb.RULESET_ROOT, vb.RULESET_PROTOCOL_FIX):
            check = _check_ruleset(ruleset, output_values, output_scripts, marker, fee)
            if metadata_error is not None:
                check = RulesetCheck(ruleset, False, check.reasons + (f"metadata: {metadata_error}",))
            checks.append(check)
        if block_time is not None and block_time < ROOT_COMMIT_TIME:
            checks = [
                RulesetCheck(c.ruleset, False, c.reasons + ("confirmed before the root commit",))
                for c in checks
            ]

    colored = tuple(range(marker)) if marker else ()
    return CandidateAssessment(
        txid=txid,
        block_height=block_height,
        block_time=block_time,
        marker_index=marker,
        first_marker_index=first_marker,
        colored_vouts=colored,
        fee_sats=fee,
        ruleset_by_date=ruleset_by_date(block_time),
        checks=tuple(checks),
        metadata_hex=metadata_hex,
        metadata_error=metadata_error,
    )


def metadata_text(metadata_hex: str | None, ruleset: str) -> str | None:
    """Printable metadata under ``ruleset`` (change hash removed, NULs stripped)."""

    if metadata_hex is None:
        return None
    raw = bytes.fromhex(metadata_hex)
    try:
        body, _change = vb.split_metadata(raw, ruleset)
    except ValueError:
        return None
    return body.rstrip(b"\x00").decode("latin-1")


# --- Forward tracing ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Segment:
    """Colored satoshis ``[start, end)`` of one output, from one genesis output."""

    start: int
    end: int
    genesis_txid: str
    genesis_vout: int
    genesis_offset: int  # position of ``start`` within the genesis output

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class Holding:
    txid: str
    vout: int
    value_sats: int
    segments: tuple[Segment, ...]
    block_height: int | None
    verified: bool | None  # find_genesis cross-check of each segment's first satoshi

    @property
    def colored_sats(self) -> int:
        return sum(s.size for s in self.segments)


@dataclass(frozen=True, slots=True)
class FeeLoss:
    txid: str
    segment: Segment


@dataclass(slots=True)
class LineageResult:
    genesis_txid: str
    issued_sats: int
    holdings: list[Holding] = field(default_factory=list)
    fee_losses: list[FeeLoss] = field(default_factory=list)
    transactions_visited: int = 0
    truncated: bool = False
    missing: list[str] = field(default_factory=list)

    @property
    def held_sats(self) -> int:
        return sum(h.colored_sats for h in self.holdings)

    @property
    def burned_sats(self) -> int:
        return sum(f.segment.size for f in self.fee_losses)


def map_segments_through(
    segments: Sequence[Segment],
    input_base: int,
    output_values: Sequence[int],
) -> tuple[dict[int, list[Segment]], list[Segment]]:
    """Carry segments of one input into a spending transaction's outputs.

    ``input_base`` is the sum of the values of the inputs before this one.
    Returns segments per output (positions within that output) and the parts
    that fall beyond the last output, i.e. into the fee.
    """

    out: dict[int, list[Segment]] = {}
    fee: list[Segment] = []
    for seg in segments:
        start, end = input_base + seg.start, input_base + seg.end
        cursor = 0
        for vout, value in enumerate(output_values):
            lo, hi = max(start, cursor), min(end, cursor + value)
            if lo < hi:
                out.setdefault(vout, []).append(
                    Segment(lo - cursor, hi - cursor, seg.genesis_txid, seg.genesis_vout,
                            seg.genesis_offset + (lo - start))
                )
            cursor += value
        if end > cursor:
            lo = max(start, cursor)
            fee.append(Segment(lo - cursor, end - cursor, seg.genesis_txid, seg.genesis_vout,
                               seg.genesis_offset + (lo - start)))
    return out, fee


class Vbuterin2013Census:
    """Follow the colored satoshis of a genesis forward to current holders."""

    def __init__(self, source: TransactionSource, *, max_transactions: int = 5000, verify: bool = True):
        self.source = source
        self.max_transactions = max_transactions
        self.verify = verify

    def _tx(self, txid: str) -> TxRecord | None:
        return self.source.get_transaction(txid)

    def _lookup(self, txid: str):
        tx = self._tx(txid)
        if tx is None:
            raise LookupError(txid)
        inputs = [(None, 0)] if tx.is_coinbase else [(i.prev_txid, i.prev_vout) for i in tx.inputs]
        return (
            [o.script_pubkey_hex for o in tx.outputs],
            [o.value_sats for o in tx.outputs],
            inputs,
        )

    def _verify(self, holding_txid: str, vout: int, segments: Sequence[Segment]) -> bool | None:
        if not self.verify:
            return None
        try:
            for seg in segments:
                if holding_txid == seg.genesis_txid and vout == seg.genesis_vout:
                    continue  # an unspent genesis output is its own origin
                found = vb.find_genesis(self._lookup, holding_txid, vout, seg.start)
                if found != (seg.genesis_txid, vb.FlowPosition(seg.genesis_vout, seg.genesis_offset)):
                    return False
        except LookupError:
            return None
        return True

    def trace(self, genesis_txid: str, colored_vouts: Sequence[int]) -> LineageResult:
        genesis = self._tx(genesis_txid)
        if genesis is None:
            result = LineageResult(genesis_txid, 0)
            result.missing.append(genesis_txid)
            return result

        frontier: dict[tuple[str, int], list[Segment]] = {
            (genesis_txid, v): [Segment(0, genesis.outputs[v].value_sats, genesis_txid, v, 0)]
            for v in colored_vouts
        }
        result = LineageResult(genesis_txid, sum(genesis.outputs[v].value_sats for v in colored_vouts))
        heights = {genesis_txid: genesis.block_height}
        order = {genesis_txid: genesis.historical_sort_key()}
        values = {genesis_txid: [o.value_sats for o in genesis.outputs]}
        visited: set[str] = set()

        while frontier:
            # Chain order (height, position in block), so a transaction's outputs
            # are processed after every colored input of it has been mapped.
            (txid, vout), segments = min(frontier.items(), key=lambda kv: (order[kv[0][0]], kv[0][1]))
            del frontier[(txid, vout)]
            spender_id = self.source.get_spender(txid, vout)
            if spender_id is None:
                result.holdings.append(
                    Holding(txid, vout, values[txid][vout], tuple(segments), heights.get(txid),
                            self._verify(txid, vout, segments))
                )
                continue
            if spender_id not in visited and len(visited) >= self.max_transactions:
                result.truncated = True
                result.holdings.append(
                    Holding(txid, vout, values[txid][vout], tuple(segments), heights.get(txid), None)
                )
                continue
            spender = self._tx(spender_id)
            if spender is None:
                result.missing.append(spender_id)
                continue
            visited.add(spender_id)
            heights[spender_id] = spender.block_height
            order[spender_id] = spender.historical_sort_key()
            values[spender_id] = [o.value_sats for o in spender.outputs]

            base = 0
            input_index = None
            for idx, txin in enumerate(spender.inputs):
                if (txin.prev_txid, txin.prev_vout) == (txid, vout):
                    input_index = idx
                    break
                parent = self._tx(txin.prev_txid)
                if parent is None:
                    result.missing.append(txin.prev_txid)
                    break
                base += parent.outputs[txin.prev_vout].value_sats
            if input_index is None:
                continue

            mapped, fee = map_segments_through(segments, base, values[spender_id])
            result.fee_losses.extend(FeeLoss(spender_id, s) for s in fee)
            for out_vout, segs in mapped.items():
                frontier.setdefault((spender_id, out_vout), []).extend(segs)

        result.transactions_visited = len(visited)
        merged: dict[tuple[str, int], Holding] = {}
        for h in result.holdings:
            prev = merged.get((h.txid, h.vout))
            if prev is None:
                merged[(h.txid, h.vout)] = h
            else:
                verified = None if None in (prev.verified, h.verified) else prev.verified and h.verified
                merged[(h.txid, h.vout)] = Holding(h.txid, h.vout, h.value_sats, prev.segments + h.segments,
                                                   h.block_height, verified)
        result.holdings = sorted(merged.values(), key=lambda h: (order.get(h.txid, (0, 0, "")), h.vout))
        return result
