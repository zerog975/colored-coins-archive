# Compatibility Ledger

Every modern change must be documented here, per ruleset.

## killerstorm `cbtc`, 2012-09-04

| Component | Historical behavior | Modern implementation | Semantic change? | Reason |
|---|---|---|---|---|
| Bitcoin node interface | Patched Bitcoin-Qt node | Read-only Esplora adapter (`indexer/sources/esplora.py`) | No | Data access only |
| Coloring kernel | `CTransaction::ComputeColor`, whole-transaction color | `indexer/protocols/cbtc_2012.py` | No | — |
| Output color | Not stored; color is per transaction | `all_outputs_share_transaction_color` projection | No (explicit projection) | Output-level indexing convenience |
| Census traversal | Recursive parent resolution | Forward propagation from genesis (`indexer/cbtc_census.py`) | No (equivalent frontier) | Avoids scanning unrelated ancestry |

## vbuterin/coloredcoins, 2013-09-27 and 2013-10-01

Defect numbers refer to the table in `docs/reconstruction/VBUTERIN_2013_KERNEL.md`.

| Component | Historical behavior | Modern implementation | Semantic change? | Reason |
|---|---|---|---|---|
| Bitcoin node interface | bitcoind RPC plus blockexplorer/blockchain.info/Electrum via node-sx | None yet | — | — |
| Transaction parsing | `sx showtx` addresses from libbitcoin `extract()`: P2PKH, P2PK (hash160 of the pushed key), P2SH (version 5), plus `pubkey_hash_sig` / `script_code_sig` patterns; a truncated push makes `showtx` reject the whole transaction (libbitcoin before `1deb4ab6e`, 2013-10-24, assumed for the commit window; later builds read such scripts as `raw_data`) | `historical_address_hash` covers P2PKH, P2PK (direct push) and P2SH; `script_parses_2013` rejects truncated pushes | **Yes, documented** | The two rare `*_sig` patterns and a possible assert failure on a leading `0xbb` byte are not reproduced; such outputs raise or decode differently |
| Coloring kernel | `get_parent_helper` as written returns input 0 for every lookup (hoisted `offset` and variadic `sx.add` give `NaN` or a string; defects 1, 1a) | `trace_to_parent` implements the intended offset walk; `historical_parent_helper_as_executed` reproduces the observed value exactly | **Yes, documented** | The as-written code cannot trace any colored satoshi |
| Offset boundary | Loop advances while `offset > value` (defect 12) | Advances while `position >= value`; offsets must satisfy `0 <= offset < output value` | **Yes, documented** | Offsets are read as 0-based (inferred from the `find_current_owner` default `offset = 0`); under that reading `>` leaks color by one satoshi across inputs. `>` would be correct for 1-based offsets |
| Past the last input | `TypeError` (defect 14) | `trace_to_parent` returns `None`; `find_genesis` reports no genesis | **Yes, documented** | Error path replaced by an explicit result |
| Genesis search | `find_genesis_helper`'s `prevtxobj.outputs.length` read throws `TypeError` (`prevtxobj` is an output object, so `.outputs` is undefined) inside node-sx `showtx`'s try/catch: commits 1–2 log it and never call back, commits 3–10 (async 0.2.x) crash with `Callback was already called.`; it compares an input index to the marker position; a coinbase aborts with error `"Coinbase"` (defects 2–4, 11) | `find_genesis` uses the parent output's `vout` and returns `None` at a coinbase | **Yes, documented** | Intent recovered from comments and API names |
| Forward tracing | `get_child_helper` / `find_current_owner` (defects 4, 7) | Not implemented | — | No unambiguous intent recoverable |
| Metadata retrieval | Concatenates address hashes after the first marker, including change | `get_metadata_as_historical` (exact for parseable transactions); `split_metadata` (modern, labelled) | No, except the unreproduced parsing cases in the Transaction parsing row | — |
| Metadata encoding | JavaScript string, `charCodeAt` per character | Bytes | No for U+0000..U+00FF | Characters above U+00FF were not representable historically |
| Address handling | Base58Check via `sx` CLI | Pure Python Base58Check; RIPEMD-160 from OpenSSL with a pure-Python fallback | No | Verified against the marker constant, an independent reference address and RIPEMD-160 test vectors |
| Transaction builders | Commits 1–2: `mkgenesis` and `m.send` build, sign (`sx.sign_tx_inputs`) and broadcast (`m.sendtx`). Commits 3–10: `mkgenesis(h, …)` and `mksend` only build an unsigned transaction and return `{tx, utxo}`. Many commits cannot run as written (defects 8–10a) | `plan_genesis_outputs`, `plan_send_outputs` return output layouts only | **Yes, documented** | No signing or broadcast by project rule; layouts taken from the output lists |
| Excess handling | node-sx `a7cc669` adds `in - out - fee` to `outs[excessIndex]` with no check (inputs selected for the fee only); `8654f33` and later select inputs for outputs + fee; `m.send` / `mksend` refuse when funds are short | Genesis: negative excess allowed down to a zero-value output, and rejected when `commit` maps to node-sx later than `a7cc669`; send: negative excess rejected | No | Mirrors the respective historical behavior. A negative value historically reached `sx mktx` unchanged (node-sx `sanitize` keeps `-`; `boost::lexical_cast<uint64_t>` wraps it), was serialized as a negative 64-bit output and would be rejected by nodes, so no on-chain transaction could result; the kernel raises `ValueError` instead |
| Fee | `10000 * ceil(hexlen / 2048)` on the unsigned trial transaction; under `fb3c847` the loop never ends once a trial of 2048·k hex chars repeats at multiplier k (defect 13) | `historical_fee(bytes, commit)`; raises `NonTerminatingFeeLoop` for sizes that are multiples of 1024 bytes under `fb3c847` | No | Models a size stable across retries; the historical multiplier never decreases |

Details: `docs/reconstruction/VBUTERIN_2013_KERNEL.md`.
