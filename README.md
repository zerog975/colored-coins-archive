# Colored Coins Revival

A historically faithful revival project for early Bitcoin Colored Coins.

## Core principle

This project distinguishes **historical artifacts** from **modern compatibility work**.

Historical source code, specifications, transaction references, hashes, and archived material must be preserved without modification. Modern code lives separately and must document exactly which historical behavior it reproduces or intentionally changes.

## Initial historical anchors

1. Meni Rosenfeld, *Overview of Colored Coins* (December 2012).
2. The early Colored Coins protocol/specification lineage attributed to Meni Rosenfeld, Yoni Assia, Vitalik Buterin and collaborators.
3. `vbuterin/coloredcoins`, a surviving 2013 implementation repository licensed public-domain/MIT.
4. Open Assets Protocol, a later Bitcoin-based Colored Coins implementation/evolution.

## Current status

| Ruleset | Kernel | Evidence | Chain state |
|---|---|---|---|
| killerstorm `cbtc`, September 2012 (whole-transaction coloring) | `indexer/protocols/cbtc_2012.py` | `docs/reconstruction/CBTC_2012_KERNEL.md` | testnet3 lineage reconstructed, census v0.1 frozen |
| vbuterin/coloredcoins, Sept–Oct 2013 (marker address + vertical flow) | `indexer/protocols/vbuterin_2013.py` | `docs/reconstruction/VBUTERIN_2013_KERNEL.md` | source archived as a Git bundle; no chain census yet |
| Order-based weak coloring / ArmoryX, 2012 | — | `docs/provenance/ORDER_BASED_WEAK_COLORING_2012.md` | provenance only in `main` |

All kernels are read-only. Nothing in this repository broadcasts or spends Bitcoin.

## Repository layout

- `historical/` — immutable material and machine-readable evidence:
  - `sources/` — archived historical source snapshots (Git bundles) with manifests and checksums
  - `candidates/` — verified on-chain genesis candidates
  - `census/` — frozen lineage census results
  - `test-vectors/` — deterministic vectors derived from historical sources
- `docs/` — provenance records (`provenance/`), reconstruction kernels (`reconstruction/`), roadmap, compatibility ledger and policies.
- `indexer/` — read-only transaction model, chain adapters (`sources/`), protocol kernels (`protocols/`) and census code.
- `scripts/` — command-line probes and resolvers used by the GitHub Actions workflows.
- `tests/` — unit tests; run with `python -m unittest discover -s tests -v` (Python 3.11+).

Wallet and explorer layers (roadmap Phase 3) do not exist yet.

See `docs/PRESERVATION_POLICY.md`, `docs/COMPATIBILITY.md` and `docs/ROADMAP.md`.
