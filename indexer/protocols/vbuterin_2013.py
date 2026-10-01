"""Read-only reconstruction of vbuterin/coloredcoins (September-October 2013).

Historical source:
  repository: https://github.com/vbuterin/coloredcoins
  branch: coloredcoins
  root commit: aa2bc9fb1f5cbe7035df541efe636420457f045c  (2013-09-27)
  protocol fix: debeddc6922d2a4e337dcfcb6bcb79e4eac0b13c  (2013-10-01)
  inspected tip: 6ae3d0e309543997e427942c72bb1893584ea7fe  (2013-10-06)
  archived bundle: historical/sources/vbuterin-coloredcoins-2013/

The historical implementation marks a genesis transaction with an output to
the all-zero hash160 address 1111111111111111111114oLvT2. Outputs before the
marker carry the new color, outputs after it carry metadata packed into
20-byte pseudo-hash160s, and color then follows satoshi offsets ("vertical
flow") from outputs back to inputs.

Two rulesets exist inside the surviving ten commits. They differ in where
transaction builders put excess value (change). The parsing, tracing and
metadata-reading functions are the same in all ten commits.

The historical tracing code never ran correctly as written (see
``historical_parent_helper_as_executed`` and
docs/reconstruction/VBUTERIN_2013_KERNEL.md). This module reconstructs the
*evident intent* of that code, records each deviation in
docs/COMPATIBILITY.md, and exposes as-executed behavior separately so the two
are never conflated.

The implementation is side-effect free. It never broadcasts or spends Bitcoin.
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Sequence


SOURCE_REPOSITORY = "https://github.com/vbuterin/coloredcoins"
SOURCE_BRANCH = "coloredcoins"

RULESET_ROOT = "vbuterin-coloredcoins-2013-09-27"
RULESET_PROTOCOL_FIX = "vbuterin-coloredcoins-2013-10-01"

RULESET_COMMITS = {
    RULESET_ROOT: ("aa2bc9fb1f5cbe7035df541efe636420457f045c",),
    RULESET_PROTOCOL_FIX: (
        "debeddc6922d2a4e337dcfcb6bcb79e4eac0b13c",
        "40f29a2ce1872abbfcbb332c962de34d4e2183a9",
        "72a1c4aa2f264a8952f3cbe5bc154b234a626bc4",
        "c93f8b12c4bfedd6ab29970adaf33a0871b8e063",
        "600a9156d2edc172c00907d88da2f62044414167",
        "62b431f37c27b7bdd0bef8fcc300f78c59e795c8",
        "4579b8e0293410ddbee002003f854fc9c77efcbf",
        "81815df28236a9b7dedf309a2df4a9d38fcfc2a7",
        "6ae3d0e309543997e427942c72bb1893584ea7fe",
    ),
}

# node-sx revisions assumed for each coloredcoins commit. main.js loads
# require('../node-sx'), a local checkout, so the code that actually ran is not
# recorded; this pairing is an inference documented in
# docs/reconstruction/VBUTERIN_2013_KERNEL.md ("Dependencies").
NODE_SX_A7CC669 = "a7cc669241c4051ace2494c9f5ec38863645c378"
NODE_SX_FB3C847 = "fb3c847fefed9070735c64473e28f875169a7744"
NODE_SX_FOR_COMMIT = {
    "aa2bc9fb1f5cbe7035df541efe636420457f045c": NODE_SX_A7CC669,
    "debeddc6922d2a4e337dcfcb6bcb79e4eac0b13c": NODE_SX_A7CC669,
    **{c: NODE_SX_FB3C847 for c in RULESET_COMMITS[RULESET_PROTOCOL_FIX][1:]},
}

MARKER_ADDRESS = "1111111111111111111114oLvT2"
MARKER_HASH160 = bytes(20)
MARKER_SCRIPT_HEX = "76a914" + MARKER_HASH160.hex() + "88ac"

# Every output the historical builders create starts at 10000 satoshis.
HISTORICAL_OUTPUT_VALUE = 10000
METADATA_CHUNK_BYTES = 20

ADDRESS_VERSION_PUBKEY_HASH = 0
ADDRESS_VERSION_SCRIPT_HASH = 5

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def ruleset_for_commit(commit: str) -> str:
    """Return the ruleset ID that applies to a historical source commit."""

    commit = commit.strip().lower()
    for ruleset, commits in RULESET_COMMITS.items():
        if commit in commits:
            return ruleset
    raise ValueError(f"not a surviving vbuterin/coloredcoins commit: {commit}")


# --- Hashing ----------------------------------------------------------------

# Pure-Python RIPEMD-160, used only when the local OpenSSL does not provide it.
_RMD_RL = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
    (7, 4, 13, 1, 10, 6, 15, 3, 12, 0, 9, 5, 2, 14, 11, 8),
    (3, 10, 14, 4, 9, 15, 8, 1, 2, 7, 0, 6, 13, 11, 5, 12),
    (1, 9, 11, 10, 0, 8, 12, 4, 13, 3, 7, 15, 14, 5, 6, 2),
    (4, 0, 5, 9, 7, 12, 2, 10, 14, 1, 3, 8, 11, 6, 15, 13),
)
_RMD_RR = (
    (5, 14, 7, 0, 9, 2, 11, 4, 13, 6, 15, 8, 1, 10, 3, 12),
    (6, 11, 3, 7, 0, 13, 5, 10, 14, 15, 8, 12, 4, 9, 1, 2),
    (15, 5, 1, 3, 7, 14, 6, 9, 11, 8, 12, 2, 10, 0, 4, 13),
    (8, 6, 4, 1, 3, 11, 15, 0, 5, 12, 2, 13, 9, 7, 10, 14),
    (12, 15, 10, 4, 1, 5, 8, 7, 6, 2, 13, 14, 0, 3, 9, 11),
)
_RMD_SL = (
    (11, 14, 15, 12, 5, 8, 7, 9, 11, 13, 14, 15, 6, 7, 9, 8),
    (7, 6, 8, 13, 11, 9, 7, 15, 7, 12, 15, 9, 11, 7, 13, 12),
    (11, 13, 6, 7, 14, 9, 13, 15, 14, 8, 13, 6, 5, 12, 7, 5),
    (11, 12, 14, 15, 14, 15, 9, 8, 9, 14, 5, 6, 8, 6, 5, 12),
    (9, 15, 5, 11, 6, 8, 13, 12, 5, 12, 13, 14, 11, 8, 5, 6),
)
_RMD_SR = (
    (8, 9, 9, 11, 13, 15, 15, 5, 7, 7, 8, 11, 14, 14, 12, 6),
    (9, 13, 15, 7, 12, 8, 9, 11, 7, 7, 12, 7, 6, 15, 13, 11),
    (9, 7, 15, 11, 8, 6, 6, 14, 12, 13, 5, 14, 13, 13, 7, 5),
    (15, 5, 8, 11, 14, 14, 6, 14, 6, 9, 12, 9, 12, 5, 15, 8),
    (8, 5, 12, 9, 12, 5, 14, 6, 8, 13, 6, 5, 15, 13, 11, 11),
)
_RMD_KL = (0x00000000, 0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC, 0xA953FD4E)
_RMD_KR = (0x50A28BE6, 0x5C4DD124, 0x6D703EF3, 0x7A6D76E9, 0x00000000)


def _rmd_f(j: int, x: int, y: int, z: int) -> int:
    if j == 0:
        return x ^ y ^ z
    if j == 1:
        return (x & y) | (~x & z)
    if j == 2:
        return (x | ~y) ^ z
    if j == 3:
        return (x & z) | (y & ~z)
    return x ^ (y | ~z)


def _rol(x: int, n: int) -> int:
    x &= 0xFFFFFFFF
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _ripemd160_pure(data: bytes) -> bytes:
    h = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0]
    padded = data + b"\x80" + b"\x00" * ((55 - len(data)) % 64) + struct.pack("<Q", 8 * len(data))
    for block in range(0, len(padded), 64):
        x = struct.unpack("<16I", padded[block : block + 64])
        al, bl, cl, dl, el = h
        ar, br, cr, dr, er = h
        for j in range(5):
            for i in range(16):
                t = _rol(al + _rmd_f(j, bl, cl, dl) + x[_RMD_RL[j][i]] + _RMD_KL[j], _RMD_SL[j][i]) + el
                al, el, dl, cl, bl = el, dl, _rol(cl, 10), bl, t & 0xFFFFFFFF
                t = _rol(ar + _rmd_f(4 - j, br, cr, dr) + x[_RMD_RR[j][i]] + _RMD_KR[j], _RMD_SR[j][i]) + er
                ar, er, dr, cr, br = er, dr, _rol(cr, 10), br, t & 0xFFFFFFFF
        h = [
            (h[1] + cl + dr) & 0xFFFFFFFF,
            (h[2] + dl + er) & 0xFFFFFFFF,
            (h[3] + el + ar) & 0xFFFFFFFF,
            (h[4] + al + br) & 0xFFFFFFFF,
            (h[0] + bl + cr) & 0xFFFFFFFF,
        ]
    return struct.pack("<5I", *h)


def ripemd160(data: bytes) -> bytes:
    try:
        return hashlib.new("ripemd160", data).digest()
    except ValueError:
        return _ripemd160_pure(data)


def hash160(data: bytes) -> bytes:
    return ripemd160(hashlib.sha256(data).digest())


# --- Address and script encoding -------------------------------------------


def base58check_encode(payload: bytes, version: int = 0) -> str:
    """Encode like ``sx base58check-encode <hex> <version>``."""

    data = bytes([version]) + payload
    data += hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]
    number = int.from_bytes(data, "big")
    encoded = ""
    while number:
        number, rem = divmod(number, 58)
        encoded = _B58_ALPHABET[rem] + encoded
    leading = len(data) - len(data.lstrip(b"\x00"))
    return "1" * leading + encoded


def base58check_decode(address: str) -> tuple[int, bytes]:
    """Decode a Base58Check string into ``(version, payload)``."""

    number = 0
    for char in address:
        index = _B58_ALPHABET.find(char)
        if index < 0:
            raise ValueError(f"invalid base58 character {char!r}")
        number = number * 58 + index
    body = number.to_bytes((number.bit_length() + 7) // 8, "big")
    leading = len(address) - len(address.lstrip("1"))
    data = b"\x00" * leading + body
    if len(data) < 5:
        raise ValueError("base58check payload too short")
    payload, checksum = data[:-4], data[-4:]
    if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != checksum:
        raise ValueError("base58check checksum mismatch")
    return payload[0], payload[1:]


def p2pkh_hash160(script_pubkey_hex: str) -> bytes | None:
    """Return the hash160 of a standard P2PKH script, else None."""

    script = script_pubkey_hex.strip().lower()
    if len(script) == 50 and script.startswith("76a914") and script.endswith("88ac"):
        return bytes.fromhex(script[6:46])
    return None


def historical_address_hash(script_pubkey_hex: str) -> tuple[int, bytes] | None:
    """``(address version, hash)`` that 2013 ``sx showtx`` would report, else None.

    The historical code sees outputs only as ``sx showtx`` addresses, which
    libbitcoin's ``extract()`` (2013) derives for these output forms:

    * P2PKH ``76 a9 14 <20> 88 ac`` -> version 0, the hash;
    * P2PK, one direct push of 1-75 bytes then ``ac`` -> version 0,
      hash160 of the pushed bytes (no public-key validity check);
    * P2SH ``a9 14 <20> 87`` -> version 5, the script hash.

    libbitcoin's ``pubkey_hash_sig`` and ``script_code_sig`` patterns are not
    reproduced; such outputs, like OP_RETURN, bare multisig and nonstandard
    scripts, return None here. See docs/COMPATIBILITY.md.
    """

    hash_ = p2pkh_hash160(script_pubkey_hex)
    if hash_ is not None:
        return ADDRESS_VERSION_PUBKEY_HASH, hash_
    script = bytes.fromhex(script_pubkey_hex.strip())
    if len(script) == 23 and script[:2] == b"\xa9\x14" and script[-1] == 0x87:
        return ADDRESS_VERSION_SCRIPT_HASH, script[2:22]
    if len(script) >= 3 and 1 <= script[0] <= 75 and len(script) == script[0] + 2 and script[-1] == 0xAC:
        return ADDRESS_VERSION_PUBKEY_HASH, hash160(script[1:-1])
    return None


def script_parses_2013(script_pubkey_hex: str) -> bool:
    """False when libbitcoin ``parse_script`` would hit end-of-stream.

    A direct push 0x01-0x4b must be followed by that many bytes, and
    OP_PUSHDATA1/2/4 by a complete little-endian length and that many bytes.
    With libbitcoin before 1deb4ab6e (2013-10-24, assumed for the commit
    window) ``sx showtx`` then fails to load the whole transaction; later
    libbitcoin loads such a script as ``raw_data``, which yields no address.
    Not modelled: a script starting with 0xbb (libbitcoin ``raw_data``),
    which may also have failed in an assert-enabled build.
    """

    script = bytes.fromhex(script_pubkey_hex.strip())
    pos = 0
    while pos < len(script):
        op = script[pos]
        pos += 1
        if 1 <= op <= 0x4B:
            size = op
        elif op in (0x4C, 0x4D, 0x4E):
            width = {0x4C: 1, 0x4D: 2, 0x4E: 4}[op]
            if pos + width > len(script):
                return False
            size = int.from_bytes(script[pos : pos + width], "little")
            pos += width
        else:
            continue
        if pos + size > len(script):
            return False
        pos += size
    return True


def is_marker_script(script_pubkey_hex: str) -> bool:
    """True when the output's historical address is exactly the marker.

    Historically the comparison is on the address string, i.e. version 0 with
    an all-zero hash; a zero-hash P2SH output (a "3..." address) is not a marker.
    """

    return historical_address_hash(script_pubkey_hex) == (ADDRESS_VERSION_PUBKEY_HASH, MARKER_HASH160)


# --- Metadata ---------------------------------------------------------------


def encode_metadata_chunks(metadata: bytes) -> tuple[bytes, ...]:
    """Split metadata into 20-byte pseudo-hash160s, NUL-padding the last one.

    Historical code (``mkgenesis`` / ``mksend``)::

        for (var pos = 0; pos < metadata.length; pos += 20) {
            var mstr = metadata.substring(pos,pos+20);
            while (mstr.length < 20) mstr += '\\x00';

    Empty metadata produces no chunks. A chunk that is twenty NUL bytes
    (including a final partial chunk whose real bytes are all NUL, which
    padding fills to twenty NULs) encodes to the marker address itself; the
    builders did not filter this. The historical code
    operated on JavaScript strings through ``charCodeAt``; this reconstruction
    takes bytes, which matches it for characters U+0000..U+00FF only.
    """

    return tuple(
        metadata[pos : pos + METADATA_CHUNK_BYTES].ljust(METADATA_CHUNK_BYTES, b"\x00")
        for pos in range(0, len(metadata), METADATA_CHUNK_BYTES)
    )


def metadata_addresses(metadata: bytes) -> tuple[str, ...]:
    """Metadata chunks as the version-0 addresses the builders paid to."""

    return tuple(base58check_encode(chunk, 0) for chunk in encode_metadata_chunks(metadata))


def get_metadata_as_historical(output_scripts: Sequence[str]) -> bytes | None:
    """Reproduce ``m.get_metadata`` byte-for-byte for parseable transactions.

    * the marker is located with ``indexOf``, i.e. its FIRST occurrence;
    * every output after it is decoded to its address hash
      (``historical_address_hash``) and concatenated, whatever the version;
    * NUL padding is NOT stripped;
    * under the 2013-10-01 ruleset the mandatory change output sits after the
      metadata, so its hash is returned as a trailing 20-byte chunk.

    Returns None where the historical code reported "No metadata". Raises
    ValueError when any output script has a truncated push (``sx showtx``
    with pre-1deb4ab6e libbitcoin rejects the whole transaction) or when an
    output after the marker has no reproducible historical address
    (``decode_addr`` fails). Not reproduced: unparseable input scripts, which
    this function does not see, and the libbitcoin cases listed under
    ``script_parses_2013`` and ``historical_address_hash``.
    """

    if not all(script_parses_2013(script) for script in output_scripts):
        raise ValueError("sx showtx cannot deserialize this transaction")
    hashes = [historical_address_hash(script) for script in output_scripts]
    marker = (ADDRESS_VERSION_PUBKEY_HASH, MARKER_HASH160)
    try:
        zeropos = hashes.index(marker)
    except ValueError:
        return None
    tail = hashes[zeropos + 1 :]
    if any(h is None for h in tail):
        raise ValueError("output after marker has no reproducible historical address")
    return b"".join(h[1] for h in tail)  # type: ignore[index]


def split_metadata(raw: bytes, ruleset: str) -> tuple[bytes, bytes | None]:
    """Modern convenience: separate historical metadata from a change hash.

    Returns ``(metadata_with_padding, change_hash_or_None)``. Under the root
    ruleset there is no change output after the metadata. This split is a
    modern interpretation; ``get_metadata_as_historical`` is authoritative.
    """

    if ruleset == RULESET_ROOT:
        return raw, None
    if ruleset == RULESET_PROTOCOL_FIX:
        if len(raw) < METADATA_CHUNK_BYTES:
            raise ValueError("protocol-fix genesis must end with a change output")
        return raw[:-METADATA_CHUNK_BYTES], raw[-METADATA_CHUNK_BYTES:]
    raise ValueError(f"unknown ruleset {ruleset}")


# --- Genesis ----------------------------------------------------------------


def genesis_marker_index(output_scripts: Sequence[str]) -> int | None:
    """Marker position as ``find_genesis_helper`` computes it.

    The historical loop overwrites ``genesis_zeroaddr_pos`` on each match and
    therefore selects the LAST marker, whereas ``get_metadata`` selects the
    first. They differ when a transaction has more than one marker output,
    which the builders produce whenever a metadata chunk is twenty NUL bytes
    or a caller-supplied address is the marker.
    """

    found = None
    for index, script in enumerate(output_scripts):
        if is_marker_script(script):
            found = index
    return found


def is_colored_genesis_output(output_scripts: Sequence[str], index: int) -> bool:
    """True when output ``index`` of this transaction carries a genesis color.

    Historical condition: ``genesis_zeroaddr_pos >= 0 && previndex <
    genesis_zeroaddr_pos``.
    """

    if index < 0 or index >= len(output_scripts):
        raise IndexError("output index out of range")
    marker = genesis_marker_index(output_scripts)
    return marker is not None and index < marker


@dataclass(frozen=True, slots=True)
class PlannedOutput:
    role: str  # "colored", "marker", "metadata", "change", "recipient", "aux"
    address: str | None
    value_sats: int


def _apply_excess(outputs: list[PlannedOutput], index: int, excess: int) -> None:
    target = outputs[index]
    value = target.value_sats + excess
    if value < 0:
        raise ValueError("excess would make the output value negative")
    outputs[index] = PlannedOutput(target.role, target.address, value)


class NonTerminatingFeeLoop(ValueError):
    """The historical fee loop for this size never finishes; no transaction results."""


def historical_fee(tx_size_bytes: int, commit: str) -> int:
    """Fee chosen by node-sx ``send_to_outputs`` for an unsigned trial transaction.

    main.js (all ten commits) states the intent: "fee = 0.0001 *
    ceil(txsize / 1024 bytes)". node-sx implements it as
    ``Math.ceil(tx.length / 2048)`` on the HEX string returned by ``sx
    mktx``, so the step is every 1024 bytes of the unsigned transaction.

    * node-sx a7cc669 (assumed for commits 1-2): 10000 * ceil(hexlen / 2048).
    * node-sx fb3c847 (commits 3-10) tests ``ceil((tx.length + 2) / 2048) >
      fee_multiplier`` but then sets ``fee_multiplier = ceil(tx.length /
      2048)``. Once a trial's hex length is 2048*k while the multiplier is
      already k, the loop repeats forever. That always happens for k = 1;
      for k >= 2 it happens when the higher fee selects the same inputs, so
      the length repeats (if it pulls in more inputs the loop may finish).

    This function models a size that is stable across retries, under which a
    multiple of 1024 bytes raises NonTerminatingFeeLoop for fb3c847.
    ``fee_multiplier`` never decreases, so a real run's fee is the maximum
    reached across retries.
    """

    if tx_size_bytes <= 0:
        raise ValueError("transaction size must be positive")
    node_sx = NODE_SX_FOR_COMMIT.get(commit.strip().lower())
    if node_sx is None:
        raise ValueError(f"not a surviving vbuterin/coloredcoins commit: {commit}")
    hex_len = 2 * tx_size_bytes
    if node_sx == NODE_SX_FB3C847 and hex_len % 2048 == 0:
        raise NonTerminatingFeeLoop(f"{tx_size_bytes}-byte transaction: fee loop never terminates")
    return HISTORICAL_OUTPUT_VALUE * math.ceil(hex_len / 2048)


def plan_genesis_outputs(
    ruleset: str,
    colored_addresses: Sequence[str],
    metadata: bytes,
    *,
    excess_sats: int,
    change_address: str | None = None,
    commit: str | None = None,
) -> tuple[PlannedOutput, ...]:
    """Output layout that ``m.mkgenesis`` produced under ``ruleset``.

    ``excess_sats`` is inputs minus outputs minus fee. node-sx
    ``send_to_outputs(history, outputs, excessIndex)`` adds it to
    ``outputs[excessIndex]`` with no sufficiency check:

    * root ruleset: excessIndex 0 -- change is merged into the FIRST COLORED
      output, so that output's value is not 10000;
    * protocol-fix ruleset: a mandatory change output is appended after the
      metadata and excessIndex is the last output.

    node-sx a7cc669 selected inputs covering only the fee, so a negative
    excess is accepted as long as the receiving output stays non-negative.
    node-sx 8654f33 and later (including fb3c847) select inputs for outputs +
    fee, so excess >= 0. Pass ``commit`` to apply the assumed node-sx: under
    ``NODE_SX_FOR_COMMIT`` negative excess is possible only for commits 1-2,
    and for commit 2 that is uncertain (8654f33 followed debeddc by 116 s).
    """

    if commit is not None:
        node_sx = NODE_SX_FOR_COMMIT.get(commit.strip().lower())
        if node_sx is None:
            raise ValueError(f"not a surviving vbuterin/coloredcoins commit: {commit}")
        if ruleset_for_commit(commit) != ruleset:
            raise ValueError(f"commit {commit} does not belong to ruleset {ruleset}")
        if node_sx != NODE_SX_A7CC669 and excess_sats < 0:
            raise ValueError("node-sx at this commit selects inputs for outputs + fee; excess cannot be negative")
    if not colored_addresses:
        raise ValueError("genesis needs at least one colored output")
    outputs = [PlannedOutput("colored", a, HISTORICAL_OUTPUT_VALUE) for a in colored_addresses]
    outputs.append(PlannedOutput("marker", MARKER_ADDRESS, HISTORICAL_OUTPUT_VALUE))
    outputs += [
        PlannedOutput("metadata", a, HISTORICAL_OUTPUT_VALUE) for a in metadata_addresses(metadata)
    ]

    if ruleset == RULESET_ROOT:
        _apply_excess(outputs, 0, excess_sats)
    elif ruleset == RULESET_PROTOCOL_FIX:
        outputs.append(PlannedOutput("change", change_address, HISTORICAL_OUTPUT_VALUE))
        _apply_excess(outputs, len(outputs) - 1, excess_sats)
    else:
        raise ValueError(f"unknown ruleset {ruleset}")
    return tuple(outputs)


def plan_send_outputs(
    ruleset: str,
    recipient: str,
    metadata: bytes,
    *,
    excess_sats: int,
    aux_address: str | None = None,
) -> tuple[PlannedOutput, ...]:
    """Output layout that ``m.send`` / ``m.mksend`` intended under ``ruleset``.

    * root: ``[recipient, metadata...]`` with excess added to output 0;
    * protocol-fix: ``[recipient, aux, metadata...]`` with excess on output 1.

    Both versions guard ``if (in_value < out_value + fee) return
    cb2("Not enough funds to pay fee")``, so negative excess is rejected.
    Transfers carry no marker unless a metadata chunk is twenty NUL bytes.
    The ``mksend`` of commits 3-10 cannot run: it references undefined ``h``
    (all), ``outputs`` (commits 3-4), ``t`` and ``maddrs`` (commits 5-10),
    and helpers absent from the module (``m.getter``, ``m.plus``,
    ``m.get_enough_utxo_from_history``, ``m.mktx``). The layout here is the
    one written into its output list.
    """

    if excess_sats < 0:
        raise ValueError("Not enough funds to pay fee")
    outputs = [PlannedOutput("recipient", recipient, HISTORICAL_OUTPUT_VALUE)]
    if ruleset == RULESET_ROOT:
        excess_index = 0
    elif ruleset == RULESET_PROTOCOL_FIX:
        outputs.append(PlannedOutput("aux", aux_address, HISTORICAL_OUTPUT_VALUE))
        excess_index = 1
    else:
        raise ValueError(f"unknown ruleset {ruleset}")
    outputs += [
        PlannedOutput("metadata", a, HISTORICAL_OUTPUT_VALUE) for a in metadata_addresses(metadata)
    ]
    _apply_excess(outputs, excess_index, excess_sats)
    return tuple(outputs)


# --- Vertical flow ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FlowPosition:
    index: int
    offset: int


def trace_to_parent(
    output_values: Sequence[int],
    index: int,
    offset: int,
    input_prevout_values: Sequence[int],
) -> FlowPosition | None:
    """Intended semantics of ``m.get_parent_helper``, with 0-based offsets.

    The absolute satoshi position is the sum of values of outputs before
    ``index`` plus ``offset``; inputs are consumed in order until the
    position falls inside one.

    Offsets are read as 0-based. This is an interpretation: no source comment
    states the convention, but ``find_current_owner`` defaults to
    ``offset = 0``, which is not a valid position under 1-based offsets. The
    historical loop advances while ``offset > value``, which is right for
    1-based offsets and, under the 0-based reading, maps the first satoshi of
    input k+1 onto the out-of-range position ``value`` of input k. This
    kernel advances while ``position >= value`` (recorded deviation,
    docs/COMPATIBILITY.md).

    Returns None where the position lies beyond all input value (the
    satoshi was created from nothing or the walk would leave the inputs; the
    historical walk would have thrown a TypeError there).
    """

    if index < 0 or index >= len(output_values):
        raise IndexError("output index out of range")
    if not 0 <= offset < output_values[index]:
        raise ValueError("offset must satisfy 0 <= offset < output value")
    position = sum(output_values[:index]) + offset
    for in_index, value in enumerate(input_prevout_values):
        if position < value:
            return FlowPosition(in_index, position)
        position -= value
    return None


def _js_to_string(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, float) and math.isnan(value):
        return "NaN"
    return str(int(value))


def _js_plus(a, b):
    if isinstance(a, str) or isinstance(b, str):
        return _js_to_string(a) + _js_to_string(b)
    return a + b


def historical_parent_helper_as_executed(
    output_values: Sequence[int],
    index: int,
    offset: int,
    input_prevout_values: Sequence[int],
) -> tuple[int, float | str]:
    """What ``m.get_parent_helper`` actually computed in all ten commits.

    Two defects combine in ``var offset = txobj.outputs.slice(0,index)
    .map(sx.getter('value')).reduce(sx.add,0) + offset``:

    * the inner ``var offset`` is hoisted, so the right-hand ``offset`` is
      ``undefined``;
    * node-sx ``add`` is variadic (05f4f7d, a7cc669 and fb3c847), so as a
      ``reduce`` callback it also adds the element index and the whole array,
      turning the sum into a string for any non-empty slice.

    The position is therefore NaN for output index 0 and a non-numeric string
    ending in "undefined" for index >= 1. Either compares false with ``>``, so
    the loop never advances and every lookup returns input 0. The ``offset``
    argument is accepted only to mirror the historical signature.
    """

    if not input_prevout_values:
        raise IndexError("transaction has no inputs")
    values = list(output_values[:index])
    array_string = ",".join(_js_to_string(v) for v in values)
    acc = 0
    for k, value in enumerate(values):
        # sx.add(acc, value, k, array) == ((((0 + acc) + value) + k) + array)
        acc = _js_plus(_js_plus(_js_plus(_js_plus(0, acc), value), k), array_string)
    position = _js_plus(acc, "undefined") if isinstance(acc, str) else math.nan
    return 0, position


def find_genesis(
    lookup,
    txid: str,
    index: int,
    offset: int = 0,
    *,
    max_depth: int = 10_000,
) -> tuple[str, FlowPosition] | None:
    """Walk parents until an output before a marker is reached.

    ``lookup(txid)`` must return ``(output_scripts, output_values, inputs)``
    where ``inputs`` is a sequence of ``(prev_txid, prev_vout)``, with
    ``prev_txid`` None for a coinbase input. Mirrors the intent of
    ``find_genesis_helper``: the output being traced is itself never tested,
    only its ancestors, and reaching a coinbase means no genesis (None).
    As written, a coinbase made ``get_prevout`` fail with the error
    "Coinbase", which aborted the search before its "no genesis found"
    branch could run.
    """

    for _ in range(max_depth):
        _, values, inputs = lookup(txid)
        if not inputs or inputs[0][0] is None:
            return None
        prev_values = [lookup(prev_txid)[1][prev_vout] for prev_txid, prev_vout in inputs]
        step = trace_to_parent(values, index, offset, prev_values)
        if step is None:
            return None
        parent_txid, parent_vout = inputs[step.index]
        parent_scripts = lookup(parent_txid)[0]
        position = FlowPosition(parent_vout, step.offset)
        if is_colored_genesis_output(parent_scripts, parent_vout):
            return parent_txid, position
        txid, index, offset = parent_txid, position.index, position.offset
    raise RuntimeError("max_depth exceeded while tracing to genesis")
