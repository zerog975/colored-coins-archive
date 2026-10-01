"""Read-only Esplora-compatible Bitcoin transaction source.

Compatible with public Esplora-style endpoints such as Blockstream Explorer and
mempool.space. This adapter intentionally implements GET operations only. There
is no transaction-broadcast method.
"""

from __future__ import annotations

import json
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from indexer.model import TransactionSource, TxInput, TxOutput, TxRecord


JsonFetcher = Callable[[str], object]


class EsploraError(RuntimeError):
    """Raised when a read-only Esplora request cannot be completed."""


class EsploraSource(TransactionSource):
    """Read Bitcoin transaction data from an Esplora-compatible HTTP service."""

    def __init__(
        self,
        base_url: str,
        *,
        network_label: str,
        timeout: float = 15.0,
        resolve_tx_index: bool = True,
        fetch_json: JsonFetcher | None = None,
        request_delay: float = 0.0,
        max_retries: int = 10,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.network_label = network_label
        self.timeout = timeout
        self.resolve_tx_index = resolve_tx_index
        self._fetch_json = fetch_json or self._http_get_json
        self.request_delay = request_delay
        self.max_retries = max_retries
        self._sleep = sleep
        self._last_request = 0.0
        self._tx_cache: dict[str, TxRecord | None] = {}
        self._outspend_cache: dict[tuple[str, int], str | None] = {}
        self._block_txids_cache: dict[str, tuple[str, ...]] = {}

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _http_get_json(self, url: str) -> object:
        """GET with a minimum spacing between requests and retries on 429/5xx."""

        for attempt in range(self.max_retries + 1):
            wait = self.request_delay - (time.monotonic() - self._last_request)
            if wait > 0:
                self._sleep(wait)
            self._last_request = time.monotonic()
            try:
                return self._http_get_json_once(url)
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt == self.max_retries:
                    raise EsploraError(f"HTTP {exc.code} from {url}") from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    backoff = float(retry_after) if retry_after else 2.0 ** (attempt + 1)
                except ValueError:
                    backoff = 2.0 ** (attempt + 1)
                self._sleep(min(backoff, 600.0))
        raise AssertionError("unreachable")

    def _http_get_json_once(self, url: str) -> object:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "colored-coins-archive/0.1 read-only archaeology",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise EsploraError(f"failed to read {url}: {exc}") from exc

    def _read(self, path: str) -> object:
        return self._fetch_json(self._url(path))

    def _transaction_index(self, block_hash: str, txid: str) -> int | None:
        if not self.resolve_tx_index:
            return None

        if block_hash not in self._block_txids_cache:
            data = self._read(f"/api/block/{block_hash}/txids")
            if data is None:
                return None
            if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
                raise EsploraError("unexpected block txid response")
            self._block_txids_cache[block_hash] = tuple(data)

        try:
            return self._block_txids_cache[block_hash].index(txid)
        except ValueError:
            raise EsploraError(
                f"transaction {txid} was not present in reported block {block_hash}"
            )

    def get_transaction(self, txid: str) -> TxRecord | None:
        if txid in self._tx_cache:
            return self._tx_cache[txid]

        data = self._read(f"/api/tx/{txid}")
        if data is None:
            self._tx_cache[txid] = None
            return None
        if not isinstance(data, dict):
            raise EsploraError("unexpected transaction response")

        vin_data = data.get("vin", [])
        vout_data = data.get("vout", [])
        if not isinstance(vin_data, list) or not isinstance(vout_data, list):
            raise EsploraError("transaction vin/vout must be lists")

        is_coinbase = bool(vin_data and vin_data[0].get("is_coinbase"))
        inputs: list[TxInput] = []
        if not is_coinbase:
            for vin in vin_data:
                try:
                    inputs.append(
                        TxInput(
                            prev_txid=str(vin["txid"]),
                            prev_vout=int(vin["vout"]),
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise EsploraError("malformed transaction input") from exc

        outputs: list[TxOutput] = []
        for vout in vout_data:
            try:
                outputs.append(
                    TxOutput(
                        value_sats=int(vout["value"]),
                        script_pubkey_hex=str(vout.get("scriptpubkey", "")),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise EsploraError("malformed transaction output") from exc

        status = data.get("status") or {}
        confirmed = bool(status.get("confirmed"))
        block_hash = status.get("block_hash") if confirmed else None
        block_height = status.get("block_height") if confirmed else None
        block_time = status.get("block_time") if confirmed else None
        tx_index = None

        if block_hash:
            tx_index = self._transaction_index(str(block_hash), txid)

        record = TxRecord(
            txid=str(data.get("txid", txid)),
            is_coinbase=is_coinbase,
            inputs=tuple(inputs),
            outputs=tuple(outputs),
            block_height=int(block_height) if block_height is not None else None,
            tx_index=tx_index,
            block_hash=str(block_hash) if block_hash is not None else None,
            block_time=int(block_time) if block_time is not None else None,
        )
        self._tx_cache[txid] = record
        return record

    def address_chain_txs_page(self, address: str, last_seen_txid: str | None = None) -> list[dict]:
        """One page (newest first) of confirmed transactions involving ``address``.

        Esplora returns up to 25 transactions per page as raw JSON, including
        each input's ``prevout``. Pass the last TXID of a page to read the next.
        """

        path = f"/api/address/{address}/txs/chain"
        if last_seen_txid:
            path += f"/{last_seen_txid}"
        data = self._read(path)
        if data is None:
            return []
        if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
            raise EsploraError("unexpected address transaction page")
        return data

    def get_spender(self, txid: str, vout: int) -> str | None:
        key = (txid, vout)
        if key in self._outspend_cache:
            return self._outspend_cache[key]

        data = self._read(f"/api/tx/{txid}/outspend/{vout}")
        if data is None:
            self._outspend_cache[key] = None
            return None
        if not isinstance(data, dict):
            raise EsploraError("unexpected outspend response")

        spender = str(data["txid"]) if data.get("spent") and data.get("txid") else None
        self._outspend_cache[key] = spender
        return spender
