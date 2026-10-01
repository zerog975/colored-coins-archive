import builtins
import hashlib
import json
import math
import unittest
from pathlib import Path

from indexer.protocols import vbuterin_2013 as vb


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "historical" / "test-vectors" / "vbuterin_coloredcoins_2013.json"
MANIFEST = ROOT / "historical" / "sources" / "vbuterin-coloredcoins-2013" / "MANIFEST.json"

# Compressed secp256k1 generator point and its well-known hash160.
G_COMPRESSED = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
G_HASH160 = "751e76e8199196d454941c45d1b3a323f1433bd6"


GENESIS_P2PK = (
    "41"
    "04678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb6"
    "49f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5f"
    "ac"
)


def p2pkh(hash160: bytes) -> str:
    return "76a914" + hash160.hex() + "88ac"


def p2sh(script_hash: bytes) -> str:
    return "a914" + script_hash.hex() + "87"


class VbuterinColoredCoins2013Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_marker_constants(self):
        marker = self.data["marker"]
        self.assertEqual(vb.MARKER_ADDRESS, marker["address"])
        self.assertEqual(vb.base58check_encode(vb.MARKER_HASH160), marker["address"])
        self.assertEqual(vb.MARKER_SCRIPT_HEX, marker["script_pubkey_hex"])
        self.assertEqual(vb.base58check_decode(marker["address"]), (0, bytes(20)))

    def test_base58check_against_independent_reference(self):
        ref = self.data["base58check_reference"]
        self.assertEqual(vb.base58check_encode(bytes.fromhex(ref["hash160_hex"])), ref["address"])
        self.assertEqual(vb.base58check_decode(ref["address"])[1].hex(), ref["hash160_hex"])

    def test_base58check_rejects_bad_checksum(self):
        with self.assertRaises(ValueError):
            vb.base58check_decode("1111111111111111111114oLvT3")

    def test_ripemd160_fallback_matches_reference_vectors(self):
        self.assertEqual(vb._ripemd160_pure(b"").hex(), "9c1185a5c5e9fc54612808977ee8f548b2258d31")
        self.assertEqual(vb._ripemd160_pure(b"abc").hex(), "8eb208f7e05d987a9b044a8e98c6b087f15a0bfc")
        # Multi-block input (80 bytes): standard RIPEMD-160 test vector.
        self.assertEqual(
            vb._ripemd160_pure(b"1234567890" * 8).hex(), "9b752e45573d4b39f4dbd3323cab82bf63326bfb"
        )
        self.assertEqual(vb.hash160(bytes.fromhex(G_COMPRESSED)).hex(), G_HASH160)
        try:
            hashlib.new("ripemd160")
        except ValueError:
            return  # no OpenSSL RIPEMD-160 to cross-check against
        for length in (32, 55, 56, 63, 64, 65, 119, 120, 200):
            data = bytes((i * 7 + length) % 256 for i in range(length))
            self.assertEqual(vb._ripemd160_pure(data), hashlib.new("ripemd160", data).digest())

    def test_historical_address_hash_forms(self):
        h = bytes(range(20))
        self.assertEqual(vb.historical_address_hash(p2pkh(h)), (0, h))
        self.assertEqual(vb.historical_address_hash(p2sh(h)), (5, h))
        self.assertEqual(
            vb.historical_address_hash("21" + G_COMPRESSED + "ac"), (0, bytes.fromhex(G_HASH160))
        )
        # 65-byte uncompressed P2PK: the block-0 coinbase key and its known address.
        genesis_hash = vb.historical_address_hash(GENESIS_P2PK)
        self.assertEqual(genesis_hash, (0, bytes.fromhex("62e907b15cbf27d5425399ebf6f0fb50ebb88f18")))
        self.assertEqual(vb.base58check_encode(genesis_hash[1]), "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
        self.assertIsNone(vb.historical_address_hash("6a0474657374"))  # OP_RETURN
        self.assertIsNone(vb.historical_address_hash("4c21" + G_COMPRESSED + "ac"))  # PUSHDATA1 P2PK

    def test_zero_hash_p2sh_is_not_the_marker(self):
        self.assertFalse(vb.is_marker_script(p2sh(bytes(20))))
        self.assertTrue(vb.is_marker_script(vb.MARKER_SCRIPT_HEX))

    def test_metadata_vectors(self):
        for vector in self.data["metadata_vectors"]:
            with self.subTest(vector=vector["name"]):
                chunks = vb.encode_metadata_chunks(bytes.fromhex(vector["metadata_hex"]))
                self.assertEqual([c.hex() for c in chunks], vector["chunks_hex"])

    def test_trace_vectors(self):
        for vector in self.data["trace_vectors"]:
            with self.subTest(vector=vector["name"]):
                args = (
                    vector["output_values"],
                    vector["index"],
                    vector["offset"],
                    vector["input_prevout_values"],
                )
                if "expected_error" in vector:
                    name = vector["expected_error"]
                    with self.assertRaises(getattr(vb, name, None) or getattr(builtins, name)):
                        vb.trace_to_parent(*args)
                    continue
                actual = vb.trace_to_parent(*args)
                if vector["expected"] is None:
                    self.assertIsNone(actual)
                else:
                    self.assertEqual(actual, vb.FlowPosition(**vector["expected"]))

    def test_as_executed_parent_helper_vectors(self):
        for vector in self.data["as_executed_parent_helper_vectors"]:
            with self.subTest(vector=vector["name"]):
                index, position = vb.historical_parent_helper_as_executed(
                    vector["output_values"],
                    vector["index"],
                    vector["offset"],
                    vector["input_prevout_values"],
                )
                self.assertEqual(index, vector["expected_index"])
                if vector["expected_position"] == "NaN":
                    self.assertTrue(isinstance(position, float) and math.isnan(position))
                else:
                    self.assertEqual(position, vector["expected_position"])

    def test_genesis_layout_vectors(self):
        for vector in self.data["genesis_layout_vectors"]:
            with self.subTest(vector=vector["name"]):
                colored = ["colored-%d" % i for i in range(vector["colored_count"])]
                outputs = vb.plan_genesis_outputs(
                    vector["ruleset"],
                    colored,
                    bytes.fromhex(vector["metadata_hex"]),
                    excess_sats=vector["excess_sats"],
                    change_address="change",
                )
                self.assertEqual([o.role for o in outputs], vector["expected_roles"])
                self.assertEqual([o.value_sats for o in outputs], vector["expected_values"])
                self.assertEqual(outputs[len(colored)].address, vb.MARKER_ADDRESS)

    def test_send_layout_vectors(self):
        for vector in self.data["send_layout_vectors"]:
            with self.subTest(vector=vector["name"]):
                outputs = vb.plan_send_outputs(
                    vector["ruleset"],
                    "recipient",
                    bytes.fromhex(vector["metadata_hex"]),
                    excess_sats=vector["excess_sats"],
                    aux_address="aux",
                )
                self.assertEqual([o.role for o in outputs], vector["expected_roles"])
                self.assertEqual([o.value_sats for o in outputs], vector["expected_values"])

    def test_genesis_excess_may_not_make_output_negative(self):
        with self.assertRaises(ValueError):
            vb.plan_genesis_outputs(vb.RULESET_ROOT, ["a"], b"", excess_sats=-10001)

    def test_genesis_negative_excess_only_for_fee_only_input_selection(self):
        tip = "6ae3d0e309543997e427942c72bb1893584ea7fe"
        commit2 = "debeddc6922d2a4e337dcfcb6bcb79e4eac0b13c"
        with self.assertRaises(ValueError):
            vb.plan_genesis_outputs(vb.RULESET_PROTOCOL_FIX, ["a"], b"", excess_sats=-1,
                                    change_address="c", commit=tip)
        outputs = vb.plan_genesis_outputs(vb.RULESET_PROTOCOL_FIX, ["a"], b"", excess_sats=-1,
                                          change_address="c", commit=commit2)
        self.assertEqual(outputs[-1].value_sats, 9999)
        with self.assertRaises(ValueError):  # commit from the other ruleset
            vb.plan_genesis_outputs(vb.RULESET_ROOT, ["a"], b"", excess_sats=0, commit=tip)

    def test_send_rejects_negative_excess_like_historical_guard(self):
        for ruleset in (vb.RULESET_ROOT, vb.RULESET_PROTOCOL_FIX):
            with self.subTest(ruleset=ruleset), self.assertRaises(ValueError):
                vb.plan_send_outputs(ruleset, "r", b"", excess_sats=-1, aux_address="aux")

    def test_fee_vectors(self):
        for vector in self.data["fee_vectors"]:
            with self.subTest(vector=vector):
                if "expected_error" in vector:
                    with self.assertRaises(getattr(vb, vector["expected_error"])):
                        vb.historical_fee(vector["tx_size_bytes"], vector["commit"])
                else:
                    self.assertEqual(
                        vb.historical_fee(vector["tx_size_bytes"], vector["commit"]), vector["expected"]
                    )

    def test_get_metadata_includes_trailing_change_under_protocol_fix(self):
        metadata = b"Colored coin: GOLD-OUNCE-2013"
        change = bytes.fromhex("11" * 20)
        chunks = vb.encode_metadata_chunks(metadata)
        scripts = [p2pkh(b"\x22" * 20), vb.MARKER_SCRIPT_HEX] + [p2pkh(c) for c in chunks] + [p2pkh(change)]

        raw = vb.get_metadata_as_historical(scripts)
        self.assertEqual(raw, b"".join(chunks) + change)
        self.assertEqual(vb.split_metadata(raw, vb.RULESET_PROTOCOL_FIX), (b"".join(chunks), change))
        self.assertEqual(vb.split_metadata(raw, vb.RULESET_ROOT), (raw, None))

    def test_get_metadata_decodes_p2pk_and_p2sh_like_sx(self):
        sh = bytes([7]) * 20
        scripts = [vb.MARKER_SCRIPT_HEX, "21" + G_COMPRESSED + "ac", p2sh(sh)]
        self.assertEqual(vb.get_metadata_as_historical(scripts), bytes.fromhex(G_HASH160) + sh)

    def test_get_metadata_fails_when_sx_cannot_parse_an_output(self):
        for scripts in (
            ["05aabb", vb.MARKER_SCRIPT_HEX, p2pkh(b"A" * 20)],
            ["4c", p2pkh(b"B" * 20)],
            ["4d01", vb.MARKER_SCRIPT_HEX],
            ["4e0100", vb.MARKER_SCRIPT_HEX, p2pkh(b"A" * 20)],
        ):
            with self.subTest(scripts=scripts), self.assertRaises(ValueError):
                vb.get_metadata_as_historical(scripts)
        self.assertTrue(vb.script_parses_2013("00bb"))
        self.assertTrue(vb.script_parses_2013("4c0100"))
        # PUSHDATA2/4 lengths are little-endian, as in libbitcoin read_2_bytes / read_4_bytes.
        for script in ("4e01000000aa", "4d0100aa"):
            self.assertTrue(vb.script_parses_2013(script), script)
        for script in ("4e0100", "4e01000000", "4d000100"):
            self.assertFalse(vb.script_parses_2013(script), script)

    def test_get_metadata_without_marker(self):
        self.assertIsNone(vb.get_metadata_as_historical([p2pkh(b"\x01" * 20)]))

    def test_get_metadata_rejects_output_without_historical_address(self):
        with self.assertRaises(ValueError):
            vb.get_metadata_as_historical([vb.MARKER_SCRIPT_HEX, "6a0474657374"])

    def test_marker_first_vs_last_occurrence(self):
        scripts = [p2pkh(b"\x01" * 20), vb.MARKER_SCRIPT_HEX, p2pkh(b"\x02" * 20), vb.MARKER_SCRIPT_HEX]
        self.assertEqual(vb.genesis_marker_index(scripts), 3)
        self.assertTrue(vb.is_colored_genesis_output(scripts, 2))
        self.assertEqual(vb.get_metadata_as_historical(scripts), b"\x02" * 20 + bytes(20))

    def test_all_nul_metadata_chunk_creates_second_marker(self):
        metadata = b"A" * 20 + b"\x00"
        outputs = vb.plan_genesis_outputs(
            vb.RULESET_PROTOCOL_FIX, ["c"], metadata, excess_sats=0, change_address="x"
        )
        self.assertEqual([o.address for o in outputs].count(vb.MARKER_ADDRESS), 2)
        scripts = [
            vb.MARKER_SCRIPT_HEX if o.address == vb.MARKER_ADDRESS else p2pkh(bytes([i + 1]) * 20)
            for i, o in enumerate(outputs)
        ]
        self.assertEqual(scripts.index(vb.MARKER_SCRIPT_HEX), 1)
        self.assertEqual(vb.genesis_marker_index(scripts), 3)

    def test_colored_genesis_output(self):
        scripts = [p2pkh(b"\x01" * 20), p2pkh(b"\x02" * 20), vb.MARKER_SCRIPT_HEX, p2pkh(b"\x03" * 20)]
        self.assertEqual(
            [vb.is_colored_genesis_output(scripts, i) for i in range(4)],
            [True, True, False, False],
        )
        self.assertFalse(vb.is_colored_genesis_output([p2pkh(b"\x01" * 20)], 0))

    def test_find_genesis_follows_vertical_flow(self):
        genesis_scripts = [p2pkh(b"\x01" * 20), p2pkh(b"\x02" * 20), vb.MARKER_SCRIPT_HEX, p2pkh(b"\x0c" * 20)]
        txs = {
            "funding": ([p2pkh(b"\x0f" * 20)], [50000], [(None, 0)]),
            "genesis": (genesis_scripts, [10000, 10000, 10000, 20000], [("funding", 0)]),
            # Spends genesis:1 then genesis:0; output 0 (10000) is entirely genesis:1.
            "transfer": ([p2pkh(b"\x04" * 20), p2pkh(b"\x05" * 20)], [10000, 10000],
                         [("genesis", 1), ("genesis", 0)]),
            "transfer2": ([p2pkh(b"\x06" * 20)], [10000], [("transfer", 1)]),
        }
        lookup = txs.__getitem__

        self.assertEqual(vb.find_genesis(lookup, "transfer", 0, 500), ("genesis", vb.FlowPosition(1, 500)))
        self.assertEqual(vb.find_genesis(lookup, "transfer", 1, 0), ("genesis", vb.FlowPosition(0, 0)))
        self.assertEqual(vb.find_genesis(lookup, "transfer2", 0, 7), ("genesis", vb.FlowPosition(0, 7)))
        # Tracing the genesis marker output reaches the funding coinbase lineage.
        self.assertIsNone(vb.find_genesis(lookup, "genesis", 2, 0))

    def test_find_genesis_boundary_does_not_leak_color(self):
        # Output 1 is funded entirely by the uncolored second input. Under the
        # historical '>' boundary its first satoshi would map onto genesis:0.
        genesis_scripts = [p2pkh(b"\x01" * 20), vb.MARKER_SCRIPT_HEX]
        txs = {
            "coinbase": ([p2pkh(b"\x0f" * 20)], [50000], [(None, 0)]),
            "genesis": (genesis_scripts, [10000, 10000], [("coinbase", 0)]),
            "plain": ([p2pkh(b"\x0e" * 20)], [10000], [("coinbase", 0)]),
            "transfer": ([p2pkh(b"\x04" * 20), p2pkh(b"\x05" * 20)], [10000, 10000],
                         [("genesis", 0), ("plain", 0)]),
        }
        lookup = txs.__getitem__
        self.assertIsNone(vb.find_genesis(lookup, "transfer", 1, 0))
        self.assertEqual(vb.find_genesis(lookup, "transfer", 0, 9999), ("genesis", vb.FlowPosition(0, 9999)))

    def test_ruleset_for_commit(self):
        self.assertEqual(vb.ruleset_for_commit("aa2bc9fb1f5cbe7035df541efe636420457f045c"), vb.RULESET_ROOT)
        self.assertEqual(
            vb.ruleset_for_commit("6ae3d0e309543997e427942c72bb1893584ea7fe"), vb.RULESET_PROTOCOL_FIX
        )
        with self.assertRaises(ValueError):
            vb.ruleset_for_commit("0" * 40)

    def test_rulesets_and_node_sx_pairing_cover_the_archived_history(self):
        archived = [c["commit"] for c in self.manifest["commits"]]
        covered = [c for commits in vb.RULESET_COMMITS.values() for c in commits]
        self.assertEqual(sorted(archived), sorted(covered))
        self.assertEqual(sorted(vb.NODE_SX_FOR_COMMIT), sorted(archived))
        self.assertEqual(len(archived), 10)
        pairing = {p["coloredcoins_commit"]: p["node_sx_commit"]
                   for p in self.manifest["dependency_reference"]["assumed_pairing"]}
        self.assertEqual(pairing, vb.NODE_SX_FOR_COMMIT)

    def test_archived_bundle_matches_manifest_checksum(self):
        bundle = ROOT / self.manifest["bundle"]["path"]
        data = bundle.read_bytes()
        self.assertEqual(len(data), self.manifest["bundle"]["size_bytes"])
        self.assertEqual(hashlib.sha256(data).hexdigest(), self.manifest["bundle"]["sha256"])


if __name__ == "__main__":
    unittest.main()
