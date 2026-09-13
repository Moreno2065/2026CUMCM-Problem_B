"""Content-fingerprint snapshots of the Q2 source scope (no git in this repo).

This repository has no VCS: ``git rev-parse --is-inside-work-tree`` fails, so
commit ids and mtimes cannot be used as provenance.  This tool pins provenance
to content by hashing every in-scope source file with SHA-256.

Scope (defaults, override with ``--root`` / ``--ext``):

* ``src/q2/code/**/*.py``, ``src/q2/code/**/*.json``, ``src/q2/code/**/*.md``
* ``src/q1/code/**/*.py`` (the Q1 files Q2 actually imports)

The ``.md`` extension is part of the default scope because the round-2 baseline
``source_before.sha256`` was frozen with Q2 ``.md`` reports included.  Narrowing
the scope to ``.py``/``.json`` would report ~32 phantom ``removed`` entries and
break the before/after comparison, so the default matches the frozen baseline;
``--ext .py,.json`` reproduces the narrower reading.

Excluded subtrees: ``__pycache__``, ``.pytest_cache``,
``artifacts/gate_g_representative/``, ``q2_verification/``,
``artifacts/_legacy_superseded_v6/``, ``artifacts/q2_release_verified_v1/``,
``artifacts/q2_round2_source_snapshot/`` (the snapshot directory itself, so the
manifest never hashes itself or its report).

Subcommands
-----------
``before``  write ``source_before.sha256`` (refuses to overwrite without ``--force``)
``after``   write ``source_after.sha256``
``verify``  diff before/after: added / removed / modified lists + counts, both
            manifest fingerprints; exit code 1 when the two differ
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Iterable, Sequence

TOOL_PATH = Path(__file__).resolve()
DEFAULT_ROOT = TOOL_PATH.parents[4]
SNAPSHOT_SUBDIR = "src/q2/code/artifacts/q2_round2_source_snapshot"
BEFORE_NAME = "source_before.sha256"
AFTER_NAME = "source_after.sha256"
REPORT_NAME = "completeness_report.json"

DEFAULT_EXTENSIONS = (".py", ".json", ".md")

# ``src/q1/code`` only contributes the Python that Q2 imports.
Q1_EXTENSIONS = (".py",)

INCLUDE_ROOTS = ("src/q2/code", "src/q1/code")

EXCLUDED_PREFIXES = (
    "src/q2/code/artifacts/gate_g_representative/",
    "src/q2/code/q2_verification/",
    "src/q2/code/artifacts/_legacy_superseded_v6/",
    "src/q2/code/artifacts/q2_release_verified_v1/",
    "src/q2/code/artifacts/q2_round2_source_snapshot/",
)

EXCLUDED_PARTS = ("__pycache__", ".pytest_cache")

EXIT_OK = 0
EXIT_DIFFERENCES = 1
EXIT_USAGE = 2


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def extensions_for(rel_posix: str, q2_exts: Sequence[str]) -> Sequence[str]:
    if rel_posix.startswith("src/q1/code/"):
        return Q1_EXTENSIONS
    return q2_exts


def is_excluded(rel_posix: str) -> bool:
    if any(part in rel_posix.split("/") for part in EXCLUDED_PARTS):
        return True
    return any(rel_posix.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


def iter_scope_files(root: Path, q2_exts: Sequence[str]) -> Iterable[tuple[str, Path]]:
    """Yield ``(repo_relative_posix_path, absolute_path)`` for every in-scope file."""
    for include_root in INCLUDE_ROOTS:
        base = root / include_root
        if not base.is_dir():
            continue
        for candidate in base.rglob("*"):
            if not candidate.is_file():
                continue
            rel = candidate.relative_to(root).as_posix()
            if is_excluded(rel):
                continue
            if candidate.suffix not in extensions_for(rel, q2_exts):
                continue
            yield rel, candidate


def build_manifest(root: Path, q2_exts: Sequence[str]) -> list[tuple[str, str]]:
    entries = [(rel, sha256_file(path)) for rel, path in iter_scope_files(root, q2_exts)]
    entries.sort(key=lambda item: item[0])
    seen: dict[str, str] = {}
    for rel, digest in entries:
        if rel in seen:
            raise RuntimeError(f"duplicate scope entry: {rel}")
        seen[rel] = digest
    return entries


def render_manifest(entries: Sequence[tuple[str, str]]) -> str:
    # sha256sum "binary" layout: "<hex><space>*<path>" — byte-compatible with the
    # frozen source_before.sha256 so `sha256sum -c` works on both manifests.
    return "".join(f"{digest} *{rel}\n" for rel, digest in entries)


def parse_manifest(text: str) -> dict[str, str]:
    """Parse ``<hex> *<path>`` / ``<hex>  <path>`` / ``<hex> <path>`` lines."""
    entries: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        if " *" in line:
            digest, rel = line.split(" *", 1)
        elif "  " in line:
            digest, rel = line.split("  ", 1)
        elif " " in line:
            digest, rel = line.split(" ", 1)
        else:
            raise ValueError(f"malformed manifest line {lineno}: {raw!r}")
        digest = digest.strip().lower()
        rel = rel.strip()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"malformed digest on manifest line {lineno}: {raw!r}")
        if rel in entries:
            raise ValueError(f"duplicate manifest entry on line {lineno}: {rel}")
        entries[rel] = digest
    return entries


def load_manifest(path: Path) -> tuple[dict[str, str], str]:
    raw = path.read_bytes()
    return parse_manifest(raw.decode("utf-8")), sha256_bytes(raw)


def fingerprint_of(path: Path) -> str:
    return sha256_file(path)


def snapshot_dir(root: Path) -> Path:
    return root / SNAPSHOT_SUBDIR


def write_manifest(path: Path, root: Path, q2_exts: Sequence[str]) -> list[tuple[str, str]]:
    entries = build_manifest(root, q2_exts)
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" keeps the LF we generate verbatim (no CRLF translation).
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(render_manifest(entries))
    return entries


def diff_manifests(before: dict[str, str], after: dict[str, str]) -> dict[str, object]:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(
        rel for rel in set(before) & set(after) if before[rel] != after[rel]
    )
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified),
        },
    }


def cmd_before(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    target = snapshot_dir(root) / BEFORE_NAME
    if target.exists() and not args.force:
        print(
            f"REFUSED: {target} already exists; the round-2 baseline is frozen. "
            "Pass --force to overwrite it deliberately.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    entries = write_manifest(target, root, args.extension_tuple)
    print(f"wrote {target}")
    print(f"files: {len(entries)}")
    print(f"manifest_sha256: {fingerprint_of(target)}")
    return EXIT_OK


def cmd_after(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    target = snapshot_dir(root) / AFTER_NAME
    entries = write_manifest(target, root, args.extension_tuple)
    print(f"wrote {target}")
    print(f"files: {len(entries)}")
    print(f"manifest_sha256: {fingerprint_of(target)}")
    return EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    directory = snapshot_dir(root)
    before_path = Path(args.before) if args.before else directory / BEFORE_NAME
    after_path = Path(args.after) if args.after else directory / AFTER_NAME
    for path in (before_path, after_path):
        if not path.is_file():
            print(f"ERROR: missing manifest {path}", file=sys.stderr)
            return EXIT_USAGE

    before, before_fp = load_manifest(before_path)
    after, after_fp = load_manifest(after_path)
    result = diff_manifests(before, after)
    counts = result["counts"]
    has_differences = any(counts.values())  # type: ignore[union-attr]

    print(f"root: {root}")
    print(f"before: {before_path.as_posix()}  files={len(before)}  sha256={before_fp}")
    print(f"after:  {after_path.as_posix()}  files={len(after)}  sha256={after_fp}")
    print(f"added:    {counts['added']}")  # type: ignore[index]
    print(f"removed:  {counts['removed']}")  # type: ignore[index]
    print(f"modified: {counts['modified']}")  # type: ignore[index]
    print(f"has_differences: {has_differences}")
    for label in ("added", "removed"):
        for rel in result[label]:  # type: ignore[index]
            print(f"  {label}: {rel}")
    for rel in result["modified"]:  # type: ignore[index]
        print(f"  modified: {rel}")

    report_path = Path(args.report) if args.report else None
    if report_path is not None:
        write_report(
            report_path,
            root=root,
            before_path=before_path,
            before_fp=before_fp,
            before_count=len(before),
            after_path=after_path,
            after_fp=after_fp,
            after_count=len(after),
            result=result,
            q2_exts=args.extension_tuple,
        )
        print(f"wrote {report_path}")

    return EXIT_DIFFERENCES if has_differences else EXIT_OK


def write_report(
    report_path: Path,
    *,
    root: Path,
    before_path: Path,
    before_fp: str,
    before_count: int,
    after_path: Path,
    after_fp: str,
    after_count: int,
    result: dict[str, object],
    q2_exts: Sequence[str],
) -> None:
    counts = result["counts"]
    has_differences = any(counts.values())  # type: ignore[union-attr]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": "src/q2/code/tools/q2_snapshot_manifest.py",
        "root": str(root),
        "scope": {
            "include": [
                f"src/q2/code/**/*{ext}" for ext in q2_exts
            ]
            + [f"src/q1/code/**/*{ext}" for ext in Q1_EXTENSIONS],
            "excluded_prefixes": list(EXCLUDED_PREFIXES),
            "excluded_path_parts": list(EXCLUDED_PARTS),
        },
        "before": {
            "manifest": before_path.relative_to(root).as_posix(),
            "manifest_sha256": before_fp,
            "file_count": before_count,
        },
        "after": {
            "manifest": after_path.relative_to(root).as_posix(),
            "manifest_sha256": after_fp,
            "file_count": after_count,
        },
        "counts": counts,
        "added": result["added"],
        "removed": result["removed"],
        "modified": [
            {
                "path": rel,
                "before_sha256": None,
                "after_sha256": None,
            }
            for rel in result["modified"]  # type: ignore[index]
        ],
        "has_differences": has_differences,
        "verdict": (
            "SOURCE_SNAPSHOT_DIRTY_CONCURRENT_EDITS"
            if has_differences
            else "SOURCE_SNAPSHOT_CLEAN"
        ),
        "note": (
            "Multiple round-2 workflows edit this tree concurrently. A non-empty "
            "'modified'/'added' set is expected and is reported as-is. Any artifact "
            "produced while the tree differed from the frozen baseline is bound to "
            "the content it actually read, not to a single frozen snapshot."
        ),
    }
    # Fill in real digests for the modified entries.
    before, _ = load_manifest(root / report["before"]["manifest"])
    after, _ = load_manifest(root / report["after"]["manifest"])
    for item in report["modified"]:
        item["before_sha256"] = before.get(item["path"])
        item["after_sha256"] = after.get(item["path"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8", newline="") as handle:
        json.dump(report, handle, indent=2, sort_keys=False)
        handle.write("\n")


def parse_extensions(raw: str) -> tuple[str, ...]:
    parts = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if not token.startswith("."):
            token = "." + token
        parts.append(token)
    if not parts:
        raise argparse.ArgumentTypeError("at least one extension is required")
    return tuple(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="q2_snapshot_manifest.py",
        description=(
            "Content SHA-256 snapshots of the Q2 source scope. No git in this repo: "
            "provenance is pinned to file content, never to commit ids or mtimes."
        ),
    )
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="repository root to scan (default: %(default)s)",
    )
    parser.add_argument(
        "--ext",
        dest="extension_tuple",
        type=parse_extensions,
        default=DEFAULT_EXTENSIONS,
        help=(
            "comma-separated extensions scanned under src/q2/code "
            "(default: .py,.json,.md). src/q1/code is always scanned for .py."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_before = sub.add_parser("before", help=f"write {BEFORE_NAME}")
    p_before.add_argument("--force", action="store_true", help="overwrite an existing baseline")
    p_before.set_defaults(func=cmd_before)

    p_after = sub.add_parser("after", help=f"write {AFTER_NAME}")
    p_after.set_defaults(func=cmd_after)

    p_verify = sub.add_parser("verify", help="diff before/after manifests")
    p_verify.add_argument("--before", default=None, help=f"default: snapshot dir/{BEFORE_NAME}")
    p_verify.add_argument("--after", default=None, help=f"default: snapshot dir/{AFTER_NAME}")
    p_verify.add_argument(
        "--report",
        default=None,
        help=f"also write the completeness report JSON (e.g. .../{REPORT_NAME})",
    )
    p_verify.set_defaults(func=cmd_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.extension_tuple = tuple(args.extension_tuple)
    try:
        return int(args.func(args))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
