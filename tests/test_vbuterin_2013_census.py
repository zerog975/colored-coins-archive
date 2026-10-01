import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

from indexer.model import TxInput, TxOutput, TxRecord
from indexer.protocols import vbuterin_2013 as vb
from indexer.sources.esplora import EsploraSource
from indexer.vbuterin_2013_census import (
    PROTOCOL_FIX_COMMIT_TIME,
    ROOT_COMMIT_TIME,
    Segment,
    Vbuterin2013Census,
    assess_genesis_candidate,
    map_segments_through,
    metadata_text,
)


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "census_vbuterin_2013.py"
OCT_2013 = PROTOCOL_FIX_COMMIT_TIME + 86400


def p2pkh(byte: int) -> str:
    return "76a914" + bytes([byte]).hex() * 20 + "88ac"


def meta_scripts(metadata: bytes) -> list[str]:
    return ["76a914" + c.hex() + "88ac" for c in vb.encode_metadata_chunks(metadata)]


class MemorySource:
    def __init__(self, transactions, spenders):
        self.transactions = {tx.txid: tx for tx in transactions}
        self.spenders = spenders

    def get_transaction(self, txid):
        return self.transactions.get(txid)

    def get_spender(self, txid, vout):
        return self.spenders.get((txid, vout))


def tx(txid, inputs, outputs, height, index=1, coinbase=False):
    return TxRecord(
        txid=txid,
        is_coinbase=coinbase,
        inputs=tuple(TxInput(t, v) for t, v in inputs),
        outputs=tuple(TxOutput(value, script) for value, script in outputs),
        block_height=height,
        tx_index=index,
        block_time=OCT_2013,
    )


F, G, U, T1, T2 = ("f" * 64, "a" * 64, "e" * 64, "b" * 64, "c" * 64)

GENESIS_OUTPUTS = [
    (10000, p2pkh(1)),
    (10000, p2pkh(2)),
    (10000, vb.MARKER_SCRIPT_HEX),
    *[(10000, s) for s in meta_scripts(b"hello")],
    (950000, p2pkh(9)),  # mandatory change output, 2013-10-01 ruleset
]


def chain():
    transactions = [
        tx(F, [], [(1000000, p2pkh(15))], 100, 0, coinbase=True),
        tx(U, [], [(50000, p2pkh(14))], 101, 0, coinbase=True),
        tx(G, [(F, 0)], GENESIS_OUTPUTS, 200),
        # Spends genesis:1 (colored) then an uncolored coin; fee 5000.
        tx(T1, [(G, 1), (U, 0)], [(5000, p2pkh(3)), (50000, p2pkh(4))], 201),
        # Pays 1000 of T1:0's 5000 colored sats on; 4000 become fee.
        tx(T2, [(T1, 0)], [(1000, p2pkh(5))], 202),
    ]
    spenders = {(F, 0): G, (U, 0): T1, (G, 1): T1, (T1, 0): T2}
    return MemorySource(transactions, spenders)


class AssessmentTests(unittest.TestCase):
    def test_protocol_fix_genesis_is_consistent(self):
        values = [v for v, _ in GENESIS_OUTPUTS]
        scripts = [s for _, s in GENESIS_OUTPUTS]
        a = assess_genesis_candidate(G, values, scripts, input_values=[1000000], block_time=OCT_2013)
        self.assertEqual(a.matching_rulesets, (vb.RULESET_PROTOCOL_FIX,))
        self.assertEqual(a.colored_vouts, (0, 1))
        self.assertEqual(a.fee_sats, 10000)
        self.assertEqual(a.ruleset_by_date, vb.RULESET_PROTOCOL_FIX)
        self.assertEqual(metadata_text(a.metadata_hex, vb.RULESET_PROTOCOL_FIX), "hello")

    def test_root_genesis_is_consistent(self):
        outputs = [(10000 + 77000, p2pkh(1)), (10000, p2pkh(2)), (10000, vb.MARKER_SCRIPT_HEX)]
        a = assess_genesis_candidate(
            G, [v for v, _ in outputs], [s for _, s in outputs],
            input_values=[127000], block_time=ROOT_COMMIT_TIME + 60,
        )
        self.assertEqual(a.matching_rulesets, (vb.RULESET_ROOT,))
        self.assertEqual(a.ruleset_by_date, vb.RULESET_ROOT)

    def test_plain_burn_is_rejected(self):
        a = assess_genesis_candidate(G, [5000], [vb.MARKER_SCRIPT_HEX], block_time=OCT_2013)
        self.assertFalse(a.consistent)
        self.assertEqual(a.colored_vouts, ())

    def test_wrong_values_and_fee_are_rejected(self):
        outputs = [(12345, p2pkh(1)), (10000, vb.MARKER_SCRIPT_HEX), (999, p2pkh(9))]
        a = assess_genesis_candidate(
            G, [v for v, _ in outputs], [s for _, s in outputs],
            input_values=[30000], block_time=OCT_2013,
        )
        self.assertFalse(a.consistent)
        self.assertTrue(any("fee" in r for c in a.checks for r in c.reasons))

    def test_before_root_commit_is_rejected(self):
        values = [v for v, _ in GENESIS_OUTPUTS]
        scripts = [s for _, s in GENESIS_OUTPUTS]
        a = assess_genesis_candidate(G, values, scripts, input_values=[1000000],
                                     block_time=ROOT_COMMIT_TIME - 1)
        self.assertFalse(a.consistent)


class ForwardTracingTests(unittest.TestCase):
    def test_map_segments_through_splits_and_burns(self):
        seg = Segment(0, 10000, G, 1, 0)
        out, fee = map_segments_through([seg], 0, [4000, 3000])
        self.assertEqual(out[0], [Segment(0, 4000, G, 1, 0)])
        self.assertEqual(out[1], [Segment(0, 3000, G, 1, 4000)])
        self.assertEqual(fee, [Segment(0, 3000, G, 1, 7000)])
        out, fee = map_segments_through([seg], 2500, [5000, 10000])
        self.assertEqual(out[0], [Segment(2500, 5000, G, 1, 0)])
        self.assertEqual(out[1], [Segment(0, 7500, G, 1, 2500)])
        self.assertEqual(fee, [])

    def test_trace_finds_holders_and_fee_losses(self):
        result = Vbuterin2013Census(chain()).trace(G, (0, 1))
        holdings = {(h.txid, h.vout): h for h in result.holdings}

        self.assertEqual(result.issued_sats, 20000)
        self.assertEqual(set(holdings), {(G, 0), (T1, 1), (T2, 0)})
        self.assertEqual(holdings[(G, 0)].colored_sats, 10000)
        self.assertEqual(holdings[(T1, 1)].segments, (Segment(0, 5000, G, 1, 5000),))
        self.assertEqual(holdings[(T2, 0)].segments, (Segment(0, 1000, G, 1, 0),))
        self.assertEqual(result.burned_sats, 4000)
        self.assertEqual(result.held_sats + result.burned_sats, result.issued_sats)
        self.assertTrue(all(h.verified for h in result.holdings))
        self.assertEqual(result.transactions_visited, 2)
        self.assertFalse(result.truncated)

    def test_spending_two_colored_outputs_together(self):
        source = chain()
        merge = "d" * 64
        source.transactions[merge] = tx(merge, [(G, 0), (G, 1)], [(15000, p2pkh(6)), (4000, p2pkh(7))], 201)
        source.spenders = {(F, 0): G, (G, 0): merge, (G, 1): merge}
        result = Vbuterin2013Census(source).trace(G, (0, 1))
        holdings = {(h.txid, h.vout): h for h in result.holdings}
        self.assertEqual(holdings[(merge, 0)].segments,
                         (Segment(0, 10000, G, 0, 0), Segment(10000, 15000, G, 1, 0)))
        self.assertEqual(holdings[(merge, 1)].segments, (Segment(0, 4000, G, 1, 5000),))
        self.assertEqual(result.burned_sats, 1000)
        self.assertEqual(result.held_sats + result.burned_sats, 20000)
        self.assertTrue(all(h.verified for h in result.holdings))
        self.assertEqual(result.transactions_visited, 1)

    def test_transaction_cap_is_reported(self):
        result = Vbuterin2013Census(chain(), max_transactions=1).trace(G, (0, 1))
        self.assertTrue(result.truncated)
        self.assertEqual(result.held_sats + result.burned_sats, result.issued_sats)


class FakeFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return self.responses.get(url)


def raw_tx(txid, outputs, block_time, height, input_value=None):
    vin = [{"txid": "9" * 64, "vout": 0, "prevout": {"value": input_value}}] if input_value else []
    return {
        "txid": txid,
        "vin": vin,
        "vout": [{"value": v, "scriptpubkey": s} for v, s in outputs],
        "status": {"confirmed": True, "block_height": height, "block_time": block_time},
    }


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("census_script", SCRIPT)
        self.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.script)

    def test_address_paging_stops_at_root_commit_date(self):
        base = "https://example.invalid"
        addr = f"{base}/api/address/{vb.MARKER_ADDRESS}/txs/chain"
        newer = raw_tx("1" * 64, [(600, vb.MARKER_SCRIPT_HEX)], 1600000000, 600000)
        genesis = raw_tx(G, GENESIS_OUTPUTS, OCT_2013, 260000, input_value=1000000)
        older = raw_tx("2" * 64, [(1, vb.MARKER_SCRIPT_HEX)], ROOT_COMMIT_TIME - 10, 250000)
        fetcher = FakeFetcher({addr: [newer], f"{addr}/{'1' * 64}": [genesis, older]})
        source = EsploraSource(base, network_label="fixture", fetch_json=fetcher)
        args = SimpleNamespace(marker_address=vb.MARKER_ADDRESS, start_time=ROOT_COMMIT_TIME, end_time=1420070400, max_pages=10)

        found, stats = self.script.discover_by_address(source, args)

        self.assertEqual([a.txid for a in found], [G])
        self.assertTrue(found[0].consistent)
        self.assertEqual(stats["pages_read"], 2)
        self.assertTrue(stats["reached_start_time"])
        self.assertFalse(stats["page_limit_hit"])

    def test_page_limit_is_reported(self):
        base = "https://example.invalid"
        addr = f"{base}/api/address/{vb.MARKER_ADDRESS}/txs/chain"
        newer = raw_tx("1" * 64, [(600, vb.MARKER_SCRIPT_HEX)], 1600000000, 600000)
        source = EsploraSource(base, network_label="fixture", fetch_json=FakeFetcher({addr: [newer]}))
        args = SimpleNamespace(marker_address=vb.MARKER_ADDRESS, start_time=ROOT_COMMIT_TIME, end_time=1420070400, max_pages=1)
        _found, stats = self.script.discover_by_address(source, args)
        self.assertTrue(stats["page_limit_hit"])

    def test_failure_mid_paging_keeps_results_and_resume_point(self):
        from indexer.sources.esplora import EsploraError

        base = "https://example.invalid"
        addr = f"{base}/api/address/{vb.MARKER_ADDRESS}/txs/chain"
        genesis = raw_tx(G, GENESIS_OUTPUTS, OCT_2013, 260000, input_value=1000000)

        def fetcher(url):
            if url == addr:
                return [genesis]
            raise EsploraError("HTTP 429 from " + url)

        source = EsploraSource(base, network_label="fixture", fetch_json=fetcher)
        args = SimpleNamespace(marker_address=vb.MARKER_ADDRESS, start_time=ROOT_COMMIT_TIME,
                               end_time=1420070400, max_pages=10, start_after=None)
        found, stats = self.script.discover_by_address(source, args)
        self.assertEqual([a.txid for a in found], [G])
        self.assertIn("429", stats["error"])
        self.assertEqual(stats["resume_after"], G)

        resumed = SimpleNamespace(**{**vars(args), "start_after": G})
        source = EsploraSource(base, network_label="fixture",
                               fetch_json=FakeFetcher({f"{addr}/{G}": [raw_tx("2" * 64, [(1, vb.MARKER_SCRIPT_HEX)],
                                                                             ROOT_COMMIT_TIME - 10, 250000)]}))
        found, stats = self.script.discover_by_address(source, resumed)
        self.assertEqual(found, [])
        self.assertTrue(stats["reached_start_time"])
        self.assertIsNone(stats["resume_after"])

    def test_empty_first_page_is_an_error_not_a_result(self):
        from indexer.sources.esplora import EsploraError

        source = EsploraSource("https://example.invalid", network_label="fixture", fetch_json=FakeFetcher({}))
        args = SimpleNamespace(marker_address=vb.MARKER_ADDRESS, start_time=ROOT_COMMIT_TIME,
                               end_time=1420070400, max_pages=10)
        with self.assertRaises(EsploraError):
            self.script.discover_by_address(source, args)

    def test_scantxoutset_file_is_accepted(self):
        import json
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"unspents": [{"txid": G, "vout": 2, "height": 260000}]}, fh)
        self.assertEqual(self.script.load_candidate_txids(Path(fh.name)), [G])


if __name__ == "__main__":
    unittest.main()
