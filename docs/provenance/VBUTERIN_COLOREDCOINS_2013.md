# Provenance record: `vbuterin/coloredcoins`

Status: **VERIFIED SOURCE ARTIFACT**

This record documents the surviving public GitHub repository `vbuterin/coloredcoins` as an early 2013 Colored Coins implementation artifact. This file is a provenance record only; it does not alter or modernize the historical source.

## Canonical source

- Repository: `https://github.com/vbuterin/coloredcoins`
- Repository owner: `vbuterin`
- Repository name: `coloredcoins`
- Historical/default branch observed during retrieval: `coloredcoins`
- Retrieval date: `2026-09-13`
- Root commit: `aa2bc9fb1f5cbe7035df541efe636420457f045c`
- Root timestamp: `2013-09-27T22:09:50Z`
- Root message: `First commit`
- Tip commit inspected: `6ae3d0e309543997e427942c72bb1893584ea7fe`
- Tip timestamp: `2013-10-06T12:01:37Z`
- Tip message: `Added change address to mkgenesis`

The root commit has no parent. The inspected branch consists of exactly ten commits from the root through the tip listed below.

A second surviving ref, `master`, points to `4579b8e0293410ddbee002003f854fc9c77efcbf` (commit 8 below) and is an ancestor of the `coloredcoins` tip. It was identified during the 2026-09-30 snapshot and is preserved in the archived bundle.

## Complete surviving commit lineage

Chronological order, oldest first:

| # | Timestamp (UTC) | Commit | Message |
|---:|---|---|---|
| 1 | 2013-09-27 22:09:50 | `aa2bc9fb1f5cbe7035df541efe636420457f045c` | `First commit` |
| 2 | 2013-10-01 13:13:55 | `debeddc6922d2a4e337dcfcb6bcb79e4eac0b13c` | `Bugfixes and one protocol fix` |
| 3 | 2013-10-06 06:42:44 | `40f29a2ce1872abbfcbb332c962de34d4e2183a9` | `Made some API changes` |
| 4 | 2013-10-06 07:07:56 | `72a1c4aa2f264a8952f3cbe5bc154b234a626bc4` | `debug` |
| 5 | 2013-10-06 07:46:06 | `c93f8b12c4bfedd6ab29970adaf33a0871b8e063` | `Added logging and fixed some bugs` |
| 6 | 2013-10-06 07:57:45 | `600a9156d2edc172c00907d88da2f62044414167` | `Small bugfix` |
| 7 | 2013-10-06 08:09:33 | `62b431f37c27b7bdd0bef8fcc300f78c59e795c8` | `Fixed small bug and added readme` |
| 8 | 2013-10-06 08:12:24 | `4579b8e0293410ddbee002003f854fc9c77efcbf` | `Moved readme to license` |
| 9 | 2013-10-06 11:49:45 | `81815df28236a9b7dedf309a2df4a9d38fcfc2a7` | `Added more debug checking` |
| 10 | 2013-10-06 12:01:37 | `6ae3d0e309543997e427942c72bb1893584ea7fe` | `Added change address to mkgenesis` |

This sequence is the surviving Git-history baseline for this implementation. No future restoration work should rewrite or backdate these commits.

## Files at inspected tip

| Path | Git blob SHA |
|---|---|
| `LICENSE` | `370ff710754fbf5ae39fbf727c68a5afc2cdcb6d` |
| `apicli.py` | `9d9361de034582c81856a9969102815cefe57467` |
| `main.js` | `acd8c940482e855b871989611b693c8b801cf566` |
| `package.json` | `c625ba3202d1e7700331ccef426dbfa6c930f7db` |
| `test.js` | `1aa967b3f32a84d7430800252a592b82d45a36c3` |

These blob SHAs provide byte-level Git identities for the five files present at the inspected commit.

## License evidence

The repository's `LICENSE` declares the code public domain and provides an MIT license fallback. The MIT notice states:

- Copyright (c) 2013 Vitalik Buterin
- Permission is granted under the MIT License, subject to preservation of the copyright and permission notice.

The historical license file must be preserved verbatim with any archived source snapshot.

## Protocol observations from the inspected history

These observations are descriptive and must not be confused with a final protocol specification:

1. `package.json` at the inspected tip describes the package as `coloredcoins`, version `0.0.8`, with description `Basic colored coins implementation` and author `vbuterin`.
2. The October 1 commit is explicitly titled `Bugfixes and one protocol fix`; its diff changes genesis construction so that a mandatory change output is appended and transaction construction treats the final output as change. Before it, `mkgenesis` called node-sx `send_to_outputs` with `excessIndex = 0`, which (in node-sx `a7cc669`, committed about ten hours after the root commit and assumed for it) added the funder's change to the first colored output. The same commit also moved `m.send`'s excess from the recipient output to a new aux output 1; the commit message does not say which change is the protocol fix (see `docs/reconstruction/VBUTERIN_2013_KERNEL.md`). This is historically significant because it shows protocol behavior changed inside the surviving ten-commit window.
3. The source comments and genesis code use `1111111111111111111114oLvT2` as the marker separating colored outputs from metadata from the root commit `aa2bc9fb1f5cbe7035df541efe636420457f045c` onward. *(Corrected 2026-09-30: an earlier revision of this record dated the marker to commit `40f29a2ce1872abbfcbb332c962de34d4e2183a9`; per-commit inspection of the archived bundle shows it in all ten commits.)*
4. `main.js` contains routines named `find_genesis`, `find_current_owner`, and `get_metadata`, showing that this implementation explicitly attempted to trace a colored unit back to genesis and forward to its current owner.
5. The code uses an order/offset-based flow model across transaction inputs and outputs. Any modern reimplementation must be tested commit-by-commit where protocol behavior differs, rather than assuming the tip represents every earlier transaction.

## Archaeological implication

The existence of protocol-affecting changes means a blockchain census must be version-aware. Candidate historical transactions should be evaluated against the rule set that existed when they were created. The first scanner therefore needs at least two modes:

- **root/early rules**, beginning with the September 27 source state; and
- **post-protocol-fix rules**, beginning with the October 1 change and following the later October refinements.

The fixed marker address provides a useful on-chain search fingerprint, but a transaction matching that address alone is not sufficient evidence of a Colored Coins genesis. Output ordering, value flow, metadata layout, date, and historical rule compatibility must also be checked.

## Preservation rule

No file from the historical repository is to be silently corrected, reformatted, dependency-updated, or security-patched inside the historical archive. Modern fixes belong outside `historical/` and must reference the exact historical commit they reproduce or intentionally diverge from.

## Next archival actions

1. ~~Create an independent immutable snapshot of the complete ten-commit history through `6ae3d0e309543997e427942c72bb1893584ea7fe`.~~ Done 2026-09-30: `historical/sources/vbuterin-coloredcoins-2013/vbuterin-coloredcoins-2013.bundle` (both refs, complete history).
2. ~~Calculate and publish an independent checksum for that snapshot or Git bundle.~~ Done: SHA-256 in `historical/sources/vbuterin-coloredcoins-2013/MANIFEST.json`, checked by `tests/test_vbuterin_2013.py`.
3. ~~Extract deterministic protocol test vectors from the root, October 1 protocol-fix state, and final October 6 state.~~ Done: `historical/test-vectors/vbuterin_coloredcoins_2013.json`; kernel and defect analysis in `docs/reconstruction/VBUTERIN_2013_KERNEL.md`. The October 1 and October 6 states share one ruleset.
4. Search historical Bitcoin transactions for marker-compatible genesis candidates and validate them against the correct historical rule set.
5. Record an archive reference independent of GitHub (for example Software Heritage) for the repository.
