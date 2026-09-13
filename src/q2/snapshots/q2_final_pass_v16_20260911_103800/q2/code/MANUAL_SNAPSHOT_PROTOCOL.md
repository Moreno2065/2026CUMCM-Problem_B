# Q2 Manual Snapshot Protocol

Git is deliberately not used for this project. Traceability is maintained with immutable Gate snapshots instead.

## On each Gate PASS

1. Run the full Gate test suite and every preserved upstream regression suite.
2. Create a new, timestamped directory at `D:\CUMCM2026\snapshots\<snapshot_id>`. The destination must not already exist.
3. Copy the complete current `src/q2/` tree into that directory; never overwrite an earlier snapshot.
4. Ensure the snapshot contains the Gate `REPORT.md`, verification JSON, fixtures, and the captured test output.
5. Add `SNAPSHOT_MANIFEST.md` with only: snapshot id, creation time, Gate status, included changes, test results, and the next Gate.

## Provenance fields

Every Q2 final/run provenance payload uses:

```text
snapshot_id
snapshot_created_at
source_snapshot
verification_report
```

`source_snapshot` is `null` for the first approved Gate and otherwise identifies the last PASS snapshot used as the starting point.

## Rollback rule

Do not modify an existing PASS snapshot. If a mathematical blocker is found, copy the newest relevant PASS snapshot back into a fresh working tree, document the blocker, and resume only after the affected Gate is repaired and reverified.
