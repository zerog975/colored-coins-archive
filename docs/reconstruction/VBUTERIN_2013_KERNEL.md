# Reconstruction kernel: 2013 `vbuterin/coloredcoins`

Status: **IMPLEMENTED / TESTED / SOURCE ARCHIVED — NO CHAIN CENSUS YET**

This document defines the reconstruction kernel for Vitalik Buterin's September–October 2013 marker-address Colored Coins implementation. It re-expresses the historical rules as side-effect-free Python and records exactly where the historical code, as written, differs from its evident intent.

Provenance record: `docs/provenance/VBUTERIN_COLOREDCOINS_2013.md`.

## Historical source anchor

- repository: `https://github.com/vbuterin/coloredcoins`
- archived snapshot: `historical/sources/vbuterin-coloredcoins-2013/vbuterin-coloredcoins-2013.bundle`
- snapshot manifest (refs, commits, blob SHAs, SHA-256, node-sx pairing): `historical/sources/vbuterin-coloredcoins-2013/MANIFEST.json`
- runtime dependency consulted: `https://github.com/vbuterin/node-sx` (see [Dependencies](#dependencies-and-runtime-assumptions)); it is not archived here

Modern reconstruction code lives at `indexer/protocols/vbuterin_2013.py`. It is not historical source code.

Commits are referred to by number (1–10, oldest first) or short hash; the full list is in the manifest.

## Protocol as written

Comment in `main.js`, unchanged in all ten commits:

```
// Format
// output 0-(n-1): addresses for colored coins
// output n: 1111111111111111111114oLvT2
// output n+1+: metadata
```

1. **Marker.** `1111111111111111111114oLvT2` is the version-0 Base58Check encoding of the all-zero hash160 (script `76a914 00…00 88ac`). The marker is present from the root commit onward. The historical code compares address strings, so only that exact version-0 address is a marker.
2. **Genesis outputs.** Outputs before the marker receive the new color. Each historical output is created with 10000 satoshis.
3. **Metadata.** Metadata is cut into 20-byte chunks, the last one NUL-padded, and each chunk is paid to as if it were a P2PKH hash160. The builders do not filter chunks, so a chunk of twenty NUL bytes (including a final partial chunk whose real bytes are all NUL, which padding fills to twenty NULs) becomes a second marker output.
4. **Vertical flow.** A colored satoshi is identified by `(txid, output index, offset)`; offsets appear to be 0-based (`find_current_owner` defaults to `offset = 0`, which is not a valid position under 1-based offsets). That reading is an interpretation; no source comment states the convention. Its parent is found by adding the values of all earlier outputs to the offset and walking the inputs in order. The historical loop advances while the position is strictly greater than the current input's value, which is right for 1-based offsets and off by one under the 0-based reading (defect 12).
5. **Genesis search.** Parents are walked until an output whose index is before its transaction's marker is reached. The intended result at a coinbase is "no genesis found". As written, `get_prevout` reports a coinbase as the error `"Coinbase"`, which aborts the search before its "Reached coinbase, no genesis found" branch can run (defect 11).
6. **Metadata reading.** `get_metadata` finds the first marker and concatenates the address hashes of every later output, whatever their address version.
7. **Fee.** The stated intent is `fee = 0.0001 * ceil(txsize / 1024 bytes)`. node-sx implements it as `ceil(tx.length / 2048)` on the hex string returned by `sx mktx`, which is the same 1024-byte step.

## Rulesets

The ten surviving commits contain two rulesets. They differ in where transaction builders put excess value.

| Ruleset ID | Commits | Genesis layout | Change (excess) goes to | Transfer layout |
|---|---|---|---|---|
| `vbuterin-coloredcoins-2013-09-27` | 1 `aa2bc9f` | colored…, marker, metadata… | output 0: **the first colored output** | recipient, metadata…; change to output 0 |
| `vbuterin-coloredcoins-2013-10-01` | 2–10 `debeddc` … `6ae3d0e` | colored…, marker, metadata…, change | the last output: a mandatory change output | recipient, aux, metadata…; change to output 1 |

`mkgenesis` hands placement to node-sx `send_to_outputs(history, outputs, excessIndex)`, which (from `a7cc669` on) executes `outs[excessIndex].value += in_value - out_value - fee` with no sufficiency check. The root commit passes `excessIndex = 0` (`aa2bc9f` main.js:114), so the funder's change landed in the first genesis output and, under vertical flow, became colored. `m.send` computes its excess inline and, in the root commit, also adds it to output 0, the recipient.

Commit 2 `debeddc` (`Bugfixes and one protocol fix`) changes both builders. `mkgenesis` appends a mandatory change output and passes `t.outputs.length-1`. `m.send` inserts an aux output at index 1 and puts the excess there. The commit message does not say which change is the "one protocol fix". The `mkgenesis` change is the more likely referent, because it is the one that changes which satoshis become colored. That attribution is an interpretation, not a documented fact.

The root-ruleset arithmetic rests on node-sx `a7cc669`, which was committed about ten hours after the root commit. The node-sx committed by that date (`05f4f7d`) also aimed the excess at output 0 but cannot run (see Dependencies).

Parsing, tracing and metadata-reading code is the same in both rulesets.

## Dependencies and runtime assumptions

`package.json` (all commits) declares `underscore`, `async`, `long-stack-traces`, `crypto`, `bitcoin` and `express` 3.1.0, `engines.node "*"`, and `node-sx >= 0.0.17` (commits 1–8) or `>= 0.0.19` (commits 9–10). `main.js` actually loads `require('../node-sx')`, a local checkout, so the semver range does not identify the code that ran.

External services: two command-line tools spawned by node-sx — the libbitcoin `sx` CLI (its `blke-fetch-transaction`, `bci-fetch-last-height`, `bci-history` and `bci-pushtx` subcommands reach blockexplorer and blockchain.info; node-sx `bci_history` runs `bci-fetch-last-height` before every `bci-history`) and the Electrum client (`electrum sendrawtransaction`, called by `sx.electrum_pushtx` from `m.sendtx`) — plus a bitcoind JSON-RPC client hard-coded in `main.js`.

Assumed node-sx revision per coloredcoins commit (also in the manifest and `NODE_SX_FOR_COMMIT`):

| coloredcoins | node-sx | Basis |
|---|---|---|
| 1 `aa2bc9f` (2013-09-27 18:09 -04) | `a7cc669` (2013-09-28 04:10 -04) | Inferred. Root `main.js` calls `sx.plus`, first present in `a7cc669`. The node-sx committed by that date, `05f4f7d` (2013-09-24, same version 0.0.17), lacks `plus`, and its `send_to_outputs` throws `ReferenceError` (undeclared `h`, `cb3`, `cb2`); its excess line adds `in_value - out_value` with no `- fee` (a fee allowance is instead subtracted when it overwrites `outputs[0].value`, whatever `excessIndex` is). The working copy actually used is not recorded. |
| 2 `debeddc` (2013-10-01 09:13 -04) | `a7cc669` | By date. Ambiguous: `8654f33` (116 s later) changes input selection from `fee` to `out_value + fee`, and `2e5f44a` bumps the version to 0.0.18. |
| 3–10 `40f29a2` … `6ae3d0e` | `fb3c847` (2013-10-06 02:34 -04) | By date; these commits stop using `sx.cbmap`, which `fb3c847` removed. |

The `sx` build is assumed to use libbitcoin from before `1deb4ab6e` (2013-10-24), chosen by date to match the commit window (2013-09-27 to 2013-10-06). In that libbitcoin an output script with a truncated push makes `read_script` throw and `sx showtx` reject the whole transaction; from `1deb4ab6e` on, such scripts load as `raw_data` with no address. The `sx` and libbitcoin builds actually used are not recorded.

A Node.js reproduction environment (Phase 1 of the roadmap) has not been built.

## Historical defects (as written ≠ as intended)

The kernel implements the intent. Defects are recorded here and, where they change results, exposed as separate functions. "All" means all ten commits.

| # | Location (commits) | Defect | Effect | Kernel treatment |
|---|---|---|---|---|
| 1 | `get_parent_helper` (all) | `var offset = <sum> + offset` inside the callback is hoisted, so the right-hand `offset` is `undefined` | position is `NaN` for output index 0; see 1a for index ≥ 1. `NaN > x` is false, so every lookup returns **input 0** | `trace_to_parent` = intent; `historical_parent_helper_as_executed` = observed behavior |
| 1a | `get_parent_helper`, `get_child_helper` (all) | `.reduce(sx.add, 0)`: node-sx `add` is variadic (`05f4f7d`, `a7cc669`, `fb3c847`), so as a reduce callback it also adds the element index and the whole array (joined with commas) | the sum becomes a string for any non-empty slice (e.g. `"1000010000undefined"` for index 1); compared with `>` it is false, so input 0 is still returned. With hoisting fixed, index 1 gives a numeric string: output 0's value written twice, then the offset (e.g. `"10000100005000"`); for 10000-sat outputs that usually exceeds the inputs' total, so the walk runs past the last input (defect 14). Index ≥ 2 gives a string containing commas, which converts to `NaN`, so input 0 is still returned | intent: numeric sum; observed value reproduced exactly by `historical_parent_helper_as_executed` |
| 2 | `get_parent_helper` / `find_genesis_helper` (all) | helper returns the parent *output object*, then reads `.outputs` from it | `TypeError` on the first genesis check. It is thrown inside node-sx `showtx`'s `try { …; cb(null, ans) } catch (e) { cb(e) }`, which hands the error to the input's map callback a second time: in commits 1–2 (`sx.cbmap`, `_.once`) it is logged and `find_genesis` never calls back; in 3–10 (`async.map`, async 0.2.x) async throws `Callback was already called.`, uncaught | intent: test the parent transaction's outputs |
| 3 | `find_genesis_helper` (all) | compares the child's **input** index with the parent's marker index, and recurses with it as an output index | wrong index in both places | intent: use the parent output's `vout` |
| 4 | `find_genesis_helper`, `find_current_owner_helper`, `find_current_owner` (all) | helper calls not prefixed with `m.` (`var m = {}`) | `find_current_owner` throws `ReferenceError` (uncaught, inside the async chain) once the starting transaction has been fetched and decoded, before any hop; if the fetch or decode fails, the callback receives that error instead. The unprefixed recursion in `find_genesis_helper` would throw after one hop, but is unreachable because defect 2 throws first | intent: recursion |
| 5 | `find_genesis_helper` vs `get_metadata` (all) | the first finds the **last** marker, the second the **first** (`indexOf`) | they differ for multi-marker transactions, which the builders create when a metadata chunk is twenty NUL bytes (including a final partial chunk whose real bytes are all NUL) or a supplied address is the marker | both reproduced exactly |
| 6 | `get_metadata`, ruleset 2013-10-01 | reads every output after the marker, including the mandatory change output | returned metadata ends with the change address hash; padding not stripped | `get_metadata_as_historical` reproduces it; `split_metadata` is a labelled modern split |
| 7 | `get_child_helper`, `get_spender` (all) | `prevous` typo, `getter('values')`, `o.next_txobj` undefined, unprefixed `get_prevout`, `filter` callback with no `return`, off-by-one `out_index--`, iterates inputs instead of outputs | forward tracing (current owner) cannot run | **not reconstructed**; no unambiguous intent can be recovered |
| 8 | `mksend` (3–10) | undefined `h` (all), `outputs` (3–4), `t` and `maddrs` (5–10; the local was renamed `scope` but `t.auxaddress`, `t.testtx` and `maddrs` remained); calls `m.getter`, `m.plus`, `m.get_enough_utxo_from_history`, `m.mktx`, none defined on `m` | transfer builder cannot run. First failure: `TypeError` at `m.getter` in 3–4; `ReferenceError` on `debugmode` in 5 (defect 10); in 6–10, `ReferenceError` on `maddrs` when `txout` is a `txhash:index` string, while a non-string `txout` stalls because that branch never calls `cb2` | layout taken from its output list only |
| 9 | `mkgenesis` (3–4) | removing the `sx.addr(priv, …)` step left `function(__,cb2)` as the first `async.waterfall` task; async passes it only the callback, so `cb2` is undefined | `sx.cbsetter(t,'outputs',cb2)(null,outputs)` throws `TypeError` before any transaction is built | layout unaffected |
| 10 | `m.log` (5, `c93f8b1`) | reads bare `debugmode` instead of `m.debugmode` (fixed in `600a915`) | every `m.log` throws `ReferenceError`; `mkgenesis` fails at its first statement | layout unaffected |
| 10a | `mkgenesis` (6–9) | change output address is `t.from` / `scope.from`, whose only assignment (commit 2, `sx.addr(priv, sx.cbsetter(t,'from',cb2))`) was removed in commit 3 | node-sx `mktx` is handed the output `undefined:<value>`, which is not an address; whether `sx mktx` rejected it has not been verified. Fixed when `6ae3d0e` added the `change` parameter | layout unaffected |
| 11 | `get_prevout` → `get_parent_helper` / `find_genesis_helper` (all) | a coinbase is reported as the error `"Coinbase"`, which `async.map` / `sx.cbmap` and `eh` propagate | the search aborts with error `"Coinbase"`; the `prevtxobjs[0] == "Coinbase"` check and `"Reached coinbase, no genesis found"` are dead code | intent: no genesis, `find_genesis` returns `None` |
| 12 | `get_parent_helper` loop (all) | advances while `offset > value`; under the 0-based reading of offsets the first satoshi of input k+1 maps to the out-of-range position `value` of input k (correct if offsets were 1-based) | color can leak across an input boundary by one satoshi | `trace_to_parent` advances while `position >= value` and rejects offsets outside `0 <= offset < output value` |
| 13 | `send_to_outputs` fee loop, node-sx `fb3c847` (3–10) | tests `ceil((len+2)/2048) > fee_multiplier` but sets `fee_multiplier = ceil(len/2048)` | once a trial's hex length is 2048·k while the multiplier is already k, the loop never ends and no transaction results. Always for k = 1; for k ≥ 2 when the higher fee selects the same inputs (if it pulls in more inputs the loop can finish) | `historical_fee` models a size stable across retries and raises `NonTerminatingFeeLoop` |
| 14 | walk past the last input (all) | indexing `prevtxobjs[in_index]` beyond the inputs | `TypeError` (in the intended loop; unreachable as written because of defects 1/1a) | `trace_to_parent` returns `None` |

Consequences for archaeology:

- The as-written code could not have traced a real transfer. Any lineage claim must rely on the intended rules. It must not claim that the historical software validated anything.
- As written, `mkgenesis` could build a transaction with a valid change address only at commit 2 and commit 10, and at commit 1 only with a node-sx later than its date. Commits 3–5 crash before building anything. Commits 6–9 pass an address-less change output to `sx mktx`.
- A transfer whose metadata contains a twenty-NUL chunk carries a marker output and can look like a genesis.

## Kernel API

| Function | Purpose |
|---|---|
| `ruleset_for_commit(commit)`, `NODE_SX_FOR_COMMIT` | map a source commit to its ruleset and assumed node-sx |
| `base58check_encode` / `base58check_decode` | address encoding |
| `historical_address_hash`, `is_marker_script`, `p2pkh_hash160`, `script_parses_2013` | the address hash `sx showtx` would report (P2PKH, P2PK, P2SH); marker test; whether libbitcoin of the commit window (before `1deb4ab6e`, 2013-10-24) could parse a script |
| `encode_metadata_chunks`, `metadata_addresses` | 20-byte metadata packing |
| `get_metadata_as_historical`, `split_metadata` | metadata reading (exact for parseable transactions; see `docs/COMPATIBILITY.md`) and modern split |
| `genesis_marker_index`, `is_colored_genesis_output` | genesis classification |
| `plan_genesis_outputs`, `plan_send_outputs`, `historical_fee` | builder layouts and fee per ruleset/commit, for recognizing candidate transactions |
| `trace_to_parent`, `find_genesis` | intended vertical-flow tracing |
| `historical_parent_helper_as_executed` | the observed `NaN` / string behavior |

Fixtures and tests:

- `historical/test-vectors/vbuterin_coloredcoins_2013.json`
- `tests/test_vbuterin_2013.py` (also checks the archived bundle's SHA-256 and that the rulesets and node-sx pairing cover exactly the ten archived commits)

## Hard boundary

This kernel must not be applied to killerstorm's 2012 `cbtc` whole-transaction coloring, order-based weak coloring / ArmoryX, EPOBC, or Open Assets.

## Census tooling

`indexer/vbuterin_2013_census.py` and `scripts/census_vbuterin_2013.py` find and trace issuances (read-only):

1. **Discovery.** Page through the confirmed transactions of `1111111111111111111114oLvT2` back to the root commit date (Esplora), or read candidate TXIDs from a file. Marker outputs cannot be spent, so Bitcoin Core `scantxoutset start '["raw(76a914000000000000000000000000000000000000000088ac)"]'` lists every one of them; its JSON output is accepted directly.
2. **Assessment.** `assess_genesis_candidate` compares each candidate with both genesis layouts: 10000-sat outputs, change on output 0 (2013-09-27) or on a final change output (2013-10-01), a fee that is a multiple of 10000, decodable metadata, and confirmation after the root commit. The address is a common burn address, so most candidates are expected to fail.
3. **Forward tracing.** `Vbuterin2013Census.trace` follows colored satoshi ranges through spending transactions (the inverse of `trace_to_parent`: 0-based, half-open ranges, inputs and outputs laid end to end) to unspent holders or fees, and cross-checks every holder backwards with `find_genesis`. Transaction metadata on transfers is not interpreted.

Caps on pages and followed transactions are reported in the output (`status: incomplete`), never applied silently. The workflow `.github/workflows/vbuterin-2013-census.yml` runs the census on mainnet and testnet3 against two independent Esplora services.

## Next steps

1. Run the census workflow and compare the two services' results; record verified candidates under `historical/candidates/` and freeze the census under `historical/census/`.
2. If address paging is refused or too slow for the burn address, run `scantxoutset` on a Bitcoin Core node and pass the result with `--candidates-file`.
3. Build a Node.js reproduction environment (node-sx at the assumed revisions, a 2013 `sx`) to confirm the as-executed behavior end to end.
4. Add an independent archival reference (e.g. Software Heritage) for the bundle.
