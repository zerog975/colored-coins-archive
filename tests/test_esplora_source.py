import unittest

from indexer.sources.esplora import EsploraSource


class FakeJsonFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return self.responses.get(url)


class EsploraSourceTests(unittest.TestCase):
    def test_confirmed_transaction_and_spender(self):
        base = "https://example.invalid"
        txid = "1" * 64
        parent = "2" * 64
        spender = "3" * 64
        block_hash = "4" * 64

        fetcher = FakeJsonFetcher(
            {
                f"{base}/api/tx/{txid}": {
                    "txid": txid,
                    "vin": [
                        {
                            "txid": parent,
                            "vout": 2,
                            "is_coinbase": False,
                        }
                    ],
                    "vout": [
                        {
                            "value": 12345,
                            "scriptpubkey": "76a91400",
                        }
                    ],
                    "status": {
                        "confirmed": True,
                        "block_height": 100,
                        "block_hash": block_hash,
                        "block_time": 1340000000,
                    },
                },
                f"{base}/api/block/{block_hash}/txids": ["0" * 64, txid],
                f"{base}/api/tx/{txid}/outspend/0": {
                    "spent": True,
                    "txid": spender,
                    "vin": 0,
                },
            }
        )

        source = EsploraSource(
            base,
            network_label="fixture",
            fetch_json=fetcher,
        )
        tx = source.get_transaction(txid)

        self.assertEqual(tx.txid, txid)
        self.assertFalse(tx.is_coinbase)
        self.assertEqual(tx.inputs[0].prev_txid, parent)
        self.assertEqual(tx.inputs[0].prev_vout, 2)
        self.assertEqual(tx.outputs[0].value_sats, 12345)
        self.assertEqual(tx.block_height, 100)
        self.assertEqual(tx.tx_index, 1)
        self.assertEqual(source.get_spender(txid, 0), spender)

        # Repeated reads should use local caches rather than issue duplicate calls.
        source.get_transaction(txid)
        source.get_spender(txid, 0)
        self.assertEqual(fetcher.calls.count(f"{base}/api/tx/{txid}"), 1)
        self.assertEqual(
            fetcher.calls.count(f"{base}/api/tx/{txid}/outspend/0"),
            1,
        )

    def test_coinbase_and_unspent_output(self):
        base = "https://example.invalid"
        txid = "5" * 64
        block_hash = "6" * 64
        fetcher = FakeJsonFetcher(
            {
                f"{base}/api/tx/{txid}": {
                    "txid": txid,
                    "vin": [{"is_coinbase": True, "scriptsig": "00"}],
                    "vout": [{"value": 5000000000, "scriptpubkey": "41"}],
                    "status": {
                        "confirmed": True,
                        "block_height": 1,
                        "block_hash": block_hash,
                        "block_time": 1231469665,
                    },
                },
                f"{base}/api/block/{block_hash}/txids": [txid],
                f"{base}/api/tx/{txid}/outspend/0": {"spent": False},
            }
        )

        source = EsploraSource(
            base,
            network_label="fixture",
            fetch_json=fetcher,
        )
        tx = source.get_transaction(txid)

        self.assertTrue(tx.is_coinbase)
        self.assertEqual(tx.inputs, ())
        self.assertEqual(tx.tx_index, 0)
        self.assertIsNone(source.get_spender(txid, 0))

    def test_missing_transaction_is_explicit(self):
        source = EsploraSource(
            "https://example.invalid",
            network_label="fixture",
            fetch_json=lambda _url: None,
        )
        self.assertIsNone(source.get_transaction("7" * 64))

    def test_tx_index_lookup_can_be_disabled(self):
        base = "https://example.invalid"
        txid = "8" * 64
        block_hash = "9" * 64
        fetcher = FakeJsonFetcher(
            {
                f"{base}/api/tx/{txid}": {
                    "txid": txid,
                    "vin": [{"txid": "a" * 64, "vout": 0, "is_coinbase": False}],
                    "vout": [{"value": 1, "scriptpubkey": ""}],
                    "status": {
                        "confirmed": True,
                        "block_height": 10,
                        "block_hash": block_hash,
                        "block_time": 1340000001,
                    },
                }
            }
        )

        source = EsploraSource(
            base,
            network_label="fixture",
            resolve_tx_index=False,
            fetch_json=fetcher,
        )
        tx = source.get_transaction(txid)

        self.assertIsNone(tx.tx_index)
        self.assertNotIn(f"{base}/api/block/{block_hash}/txids", fetcher.calls)


if __name__ == "__main__":
    unittest.main()


class EsploraRetryTests(unittest.TestCase):
    def _source(self, outcomes):
        from email.message import Message
        from urllib.error import HTTPError

        sleeps = []
        source = EsploraSource("https://example.invalid", network_label="fixture",
                               max_retries=3, sleep=sleeps.append)
        calls = []

        def once(url):
            calls.append(url)
            outcome = outcomes.pop(0)
            if isinstance(outcome, int):
                headers = Message()
                if outcome == 429:
                    headers["Retry-After"] = "7"
                raise HTTPError(url, outcome, "error", headers, None)
            return outcome

        source._http_get_json_once = once
        return source, calls, sleeps

    def test_rate_limit_is_retried_with_retry_after(self):
        source, calls, sleeps = self._source([429, 503, {"ok": True}])
        self.assertEqual(source._http_get_json("u"), {"ok": True})
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [7.0, 4.0])

    def test_client_error_is_not_retried(self):
        from indexer.sources.esplora import EsploraError

        source, calls, _ = self._source([400])
        with self.assertRaises(EsploraError):
            source._http_get_json("u")
        self.assertEqual(len(calls), 1)

    def test_retries_are_bounded(self):
        from indexer.sources.esplora import EsploraError

        source, calls, _ = self._source([429] * 4)
        with self.assertRaises(EsploraError):
            source._http_get_json("u")
        self.assertEqual(len(calls), 4)
