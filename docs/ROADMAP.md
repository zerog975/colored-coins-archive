# Revival Roadmap

Status markers: **[done]**, **[in progress]**, **[open]**.

## Phase 0 — Provenance

- **[in progress]** Freeze authoritative historical sources.
  - **[done]** `vbuterin/coloredcoins` archived as a verified Git bundle (`historical/sources/vbuterin-coloredcoins-2013/`).
  - **[open]** Archive killerstorm `cbtc`, `vbuterin/BitcoinArmory` `color` and CCDSE the same way.
- **[in progress]** Record full Git commit hashes, dates, authors and licenses (see `docs/provenance/`).
- **[open]** Locate the earliest protocol document versions.
- **[in progress]** Reconstruct the claimed first Colored Coins issuance at transaction level.
  - **[done]** September 2012 `cbtc` genesis resolved on testnet3 (`historical/candidates/cbtc_2012_genesis_092ec331.json`).
  - **[open]** 2013-11-11 / block 269000 claim (see `docs/HISTORICAL_SOURCES.md`).
- **[open]** Determine whether any original Colored Coins asset had a CoinMarketCap listing/UCID.

## Phase 1 — Reproducibility

- **[open]** Build a historical development environment for the 2013 implementation (Node.js, node-sx, `sx` CLI, Electrum command-line client).
- **[done]** Record dependency/runtime assumptions for the 2013 implementation, including the assumed node-sx revision per commit (`docs/reconstruction/VBUTERIN_2013_KERNEL.md`, "Dependencies and runtime assumptions").
- **[in progress]** Add fixtures for historical Bitcoin transactions (`cbtc` 2012 done).
- **[in progress]** Produce deterministic color-calculation test vectors (`cbtc` 2012 and vbuterin 2013 done; order-based 2012 open).

## Phase 2 — Modern indexer

- **[in progress]** Connect to a Bitcoin data source (read-only Esplora adapter done; Bitcoin Core adapter open).
- **[in progress]** Scan historical Bitcoin blocks and transactions (`cbtc` 2012 testnet3 census v0.1 and vbuterin 2013 mainnet census v0.1 done; vbuterin 2013 testnet3 open).
- **[in progress]** Implement the selected historical coloring rules without changing their semantics.
  - **[done]** `cbtc` 2012 kernel, no semantic change.
  - **[done, with documented deviations]** vbuterin 2013 kernel. The as-written tracing code cannot run, so the kernel implements the intended vertical-flow and genesis-search rules; every deviation is listed in `docs/COMPATIBILITY.md`, and `historical_parent_helper_as_executed` reproduces the observed lookup. Forward tracing (`find_current_owner`) is deliberately not reconstructed because no unambiguous intent can be recovered.
- **[open]** Expose an API for color provenance and balances.

## Phase 3 — Wallet and explorer

- **[open]** Build a watch-only color-aware explorer first.
- **[open]** Add transaction construction only after parsing/indexing is validated.
- **[open]** Make ordinary-Bitcoin-spend risks explicit in wallet UX.

## Phase 4 — Public revival

- **[open]** Publish archival evidence and compatibility report.
- **[open]** Release signed/tagged binaries or packages.
- **[open]** Only then evaluate market-data/listing requests, if historically and operationally justified.
