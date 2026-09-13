# Q2 Round-2 Source Snapshot (content fingerprints)

This directory pins the Q2 round-2 source scope to **content**, not to version
control. It holds the frozen baseline, the post-round fingerprint, the diff
report, and the rules for using them.

## Files

| File | Role |
|---|---|
| `source_before.sha256` | **Frozen baseline**, captured before round-2 work started. Do not rewrite. 147 entries. |
| `source_after.sha256` | Post-round fingerprint produced by `tools/q2_snapshot_manifest.py after`. |
| `completeness_report.json` | Machine-readable before/after diff: fingerprints, `added`/`removed`/`modified` lists and counts, generation time. |
| `README.md` | This file. |

Both manifests use the `sha256sum` layout `sha256␠*path`, one entry per line,
sorted by repository-relative POSIX path, LF newlines. The writer is
byte-compatible with the frozen baseline: `sha256sum -c source_before.sha256`
works unchanged.

## Why content fingerprints instead of a commit

This repository has **no VCS** — `git rev-parse --is-inside-work-tree` fails.
There is therefore no commit id and no per-file history to point at, and mtime
cannot substitute: copying, restoring a snapshot, or a tool rewriting a file
with identical bytes all change mtime without changing what the code is.
`MANUAL_SNAPSHOT_PROTOCOL.md` reaches the same conclusion and keeps traceability
with immutable Gate snapshots instead of git. SHA-256 over file bytes is the
only stable provenance handle available, so both `source_before.sha256` and
`source_after.sha256` record it, and the manifest files themselves are
fingerprinted too.

## Baseline fingerprint

```text
file:   src/q2/code/artifacts/q2_round2_source_snapshot/source_before.sha256
sha256: e55f55265dac3799d463a0e126df37299bd715e2accfa23d4db9d22628dd6196
files:  147
```

Re-check it with:

```bash
cd /d/CUMCM2026 && sha256sum src/q2/code/artifacts/q2_round2_source_snapshot/source_before.sha256
```

If that value ever changes, the baseline was overwritten and every
before/after comparison in this directory is void until it is re-established.

## Scope

Scanned under the repository root:

* `src/q2/code/**/*.py`, `src/q2/code/**/*.json`, `src/q2/code/**/*.md`
* `src/q1/code/**/*.py` — the Q1 files Q2 actually imports

Excluded:

* `__pycache__/`, `.pytest_cache/` anywhere
* `src/q2/code/artifacts/gate_g_representative/`
* `src/q2/code/q2_verification/`
* `src/q2/code/artifacts/_legacy_superseded_v6/`
* `src/q2/code/artifacts/q2_release_verified_v1/`
* `src/q2/code/artifacts/q2_round2_source_snapshot/` (this directory — the
  manifests never hash themselves or their report)

`src/q2/formal/`, `src/q2/tests_formal/` and `src/q2/artifacts/formal/` are owned
by a separate workflow and are outside this snapshot.

`.md` is in the default scope because the frozen baseline includes the Q2
Markdown reports; dropping it would report the 32 `.md` entries as phantom
`removed` files and make the comparison meaningless. `--ext .py,.json` narrows
the scan to code and machine-readable evidence only.

## Rules for using this snapshot

1. **A modified tree is an expected, reported state — not a failure to hide.**
   Several round-2 workflows edit this tree concurrently. When
   `completeness_report.json` reports a non-empty `added`/`removed`/`modified`
   set, that is the honest result: list it, do not smooth it over.

2. **Contaminated outputs must be marked, never published on a "tests pass"
   date alone.** If the source changes while an output (test run, artifact,
   report, figure) is being produced, that output is bound to the content it
   actually read. It must be labelled as produced against a dirty/expired
   snapshot, together with which files differed, and must not be stamped with a
   fresh "verified" date and released as if it had been validated against a
   single frozen snapshot.

3. **Re-validate after the tree settles.** Once no writer is touching the scope,
   re-run `after` and `verify`; a clean pair (empty `added`/`removed`/`modified`)
   is the only state in which round-2 outputs can be attributed to one snapshot.

4. **Never rewrite `source_before.sha256`.** `before` refuses to overwrite it
   unless `--force` is passed explicitly, and `--force` is only for a
   deliberately re-baselined round.

## Commands

```bash
cd /d/CUMCM2026
PYTHONPATH=. python src/q2/code/tools/q2_snapshot_manifest.py before         # refuses: baseline is frozen
PYTHONPATH=. python src/q2/code/tools/q2_snapshot_manifest.py after
PYTHONPATH=. python src/q2/code/tools/q2_snapshot_manifest.py verify \
    --report src/q2/code/artifacts/q2_round2_source_snapshot/completeness_report.json
```

`verify` exits `0` when before and after agree, `1` when they differ, and `2` on
usage or I/O errors (missing manifest, unreadable file). It prints the counts
and the per-file `added` / `removed` / `modified` lists.
