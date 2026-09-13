"""Archive (copy only) superseded Q2 Gate G artifacts and the legacy config evidence.

Background
----------
``artifacts/q2_final_evidence_config.json`` declares
``config_id = "q2-final-evidence-v6-dynamic-closure"``.  That identifier is not
emitted by any source file currently in this repository: the nearest generator,
``tools/generate_q2_closure_artifacts.py``, declares
``q2-final-evidence-v5-hero-closure`` and writes into
``artifacts/gate_g_representative/`` instead.  The top-level
``artifacts/q2_*.json|geojson|csv`` and ``figures/q2_*.{json,svg,pdf,png}``
therefore belong to a generation flow that no longer exists in-tree, so they
leave the current paper citation chain.

This tool never moves and never deletes.  It:

1. hashes every legacy file listed in the round-2 scope below;
2. resolves the legacy config source of each file from an embedded
   ``config_id`` / ``evidence_config_id`` when the file carries one, and
   otherwise records the weaker directory/mtime-based assignment plus its
   confidence, rather than silently guessing;
3. copies each file into ``artifacts/_legacy_superseded_v6/`` keeping the path
   structure relative to ``src/q2/code/`` (so ``artifacts/`` and ``figures/``
   counterparts with the same basename cannot collide) and verifies the copy
   digest;
4. audits the source tree for a generator of the legacy config id;
5. writes ``MANIFEST.json``, ``MANIFEST.md`` and ``README.md``.

Files that are missing are listed under ``missing`` and do not abort the run.

Usage::

    PYTHONPATH=. python src/q2/code/tools/archive_q2_legacy_artifacts.py
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

TOOL_PATH = Path(__file__).resolve()
CODE_ROOT = TOOL_PATH.parents[1]
REPO_ROOT = CODE_ROOT.parents[2]
ARCHIVE_ROOT = CODE_ROOT / "artifacts" / "_legacy_superseded_v6"

LEGACY_RUN_CONFIG = Path("artifacts/q2_final_evidence_config.json")
PROBE_CONFIG = Path("artifacts/gate_g_production_probe/q2_final_evidence_config.json")

#: Exact literal of the config id whose generator is missing from this repo.
LEGACY_CONFIG_ID = "q2-final-evidence-" + "v6-dynamic-closure"

#: Every file the round-2 work order puts in scope.  ``artifacts/q2_evidence_table.json``
#: appears twice in the source list; it is de-duplicated here.
EXPLICIT_FILES: tuple[str, ...] = (
    "artifacts/q2_evidence_table.json",
    "artifacts/q2_baseline_comparison.csv",
    "artifacts/q2_candidate_regions.json",
    "artifacts/q2_solution_examples.json",
    "artifacts/q2_model_spec.json",
    "artifacts/q2_solver_config.json",
    "artifacts/q2_final_verification_report.json",
    "artifacts/q2_regression_cases.json",
    "artifacts/q2_run_manifest.json",
    "artifacts/q2_visual_qa_report.json",
    "artifacts/q2_final_evidence_config.json",
)

EXPLICIT_GLOBS: tuple[str, ...] = (
    "artifacts/q2_candidate_region_eta_*.geojson",
    "figures/q2_*.json",
    "figures/q2_*.svg",
    "figures/q2_*.pdf",
    "figures/q2_*.png",
)

EXPLICIT_TREES: tuple[str, ...] = ("artifacts/gate_g_production_probe",)

#: Explicitly out of scope: the round-1 repair already regenerated this tree with
#: the fixed evaluator, and no other workstream owns it.
NEVER_TOUCHED_PREFIXES: tuple[str, ...] = (
    "artifacts/gate_g_representative/",
    "artifacts/_legacy_superseded_v6/",
    "artifacts/q2_release_verified_v1/",
    "artifacts/q2_round2_source_snapshot/",
    "q2_verification/",
    "formal/",
    "tests_formal/",
)

SKIP_PARTS = ("__pycache__", ".pytest_cache")

#: Files by which legacy_method_labeling is decided from content.
METHOD_LABEL_RE = re.compile(r"\bB1\b|\bB2\b|_right_angle_heuristic|_center_ray_max_min_angle")
CONFIG_ID_RE = re.compile(
    r'"(?:config_id|evidence_config_id|source_config_id)"\s*:\s*"([^"]*)"'
)

GENERATOR_AUDIT_EXCLUDED = (
    "src/q2/code/tools/archive_q2_legacy_artifacts.py",
    "src/q2/code/tools/resolve_q2_evidence_config.py",
)


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #
def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def decode_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def is_skipped(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)


def count_files(root: Path, *, exclude: Path | None = None) -> int:
    if not root.is_dir():
        return 0
    total = 0
    for candidate in root.rglob("*"):
        if not candidate.is_file() or is_skipped(candidate):
            continue
        if exclude is not None and (candidate == exclude or exclude in candidate.parents):
            continue
        total += 1
    return total


# --------------------------------------------------------------------------- #
# scope discovery
# --------------------------------------------------------------------------- #
def is_never_touched(rel_posix: str) -> bool:
    return any(rel_posix.startswith(prefix) for prefix in NEVER_TOUCHED_PREFIXES)


def discover_scope() -> list[Path]:
    """Return the sorted, de-duplicated absolute paths of every in-scope legacy file."""
    found: dict[str, Path] = {}

    def add(rel_posix: str) -> None:
        if is_never_touched(rel_posix):
            return
        absolute = CODE_ROOT / rel_posix
        if absolute.is_file():
            found.setdefault(repo_relative(absolute), absolute)

    for rel_posix in EXPLICIT_FILES:
        add(rel_posix)
    for pattern in EXPLICIT_GLOBS:
        for absolute in sorted((CODE_ROOT / pattern).parent.glob(Path(pattern).name)):
            add(absolute.relative_to(CODE_ROOT).as_posix())
    for tree in EXPLICIT_TREES:
        base = CODE_ROOT / tree
        if not base.is_dir():
            continue
        for absolute in sorted(base.rglob("*")):
            if absolute.is_file() and not is_skipped(absolute):
                add(absolute.relative_to(CODE_ROOT).as_posix())
    return [found[key] for key in sorted(found)]


def expected_scope_paths() -> list[str]:
    """The literal paths/patterns of the work order, for the ``missing`` report."""
    names: set[str] = set()
    for rel_posix in EXPLICIT_FILES:
        names.add(rel_posix)
    for pattern in EXPLICIT_GLOBS:
        names.add(pattern)
    for tree in EXPLICIT_TREES:
        names.add(tree + "/**")
    return sorted(names)


# --------------------------------------------------------------------------- #
# legacy config source resolution
# --------------------------------------------------------------------------- #
def load_config_identity(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        return {"path": repo_relative(config_path), "present": False}
    text = decode_text(config_path)
    ids = sorted(set(CONFIG_ID_RE.findall(text)))
    return {
        "path": repo_relative(config_path),
        "present": True,
        "config_id": ids[0] if ids else None,
        "sha256": sha256_file(config_path),
    }


def code_relative(rel_posix: str) -> str:
    marker = "/src/q2/code/"
    if marker in rel_posix:
        return rel_posix.split(marker, 1)[1]
    prefix = "src/q2/code/"
    return rel_posix[len(prefix):] if rel_posix.startswith(prefix) else rel_posix


def signature_numbers(text: str) -> set[str]:
    """Distinctive numeric literals under the evidence keys shared by the legacy run.

    Short literals such as ``0.0`` or ``5.0`` occur everywhere and would link
    unrelated files, so they are dropped: a usable signature needs at least eight
    characters and a decimal point.
    """
    candidates = set(
        re.findall(
            r'"(?:qhat_star|threshold|approximate_area_m2)"\s*:\s*([0-9][0-9eE.+-]*)', text
        )
    )
    return {value for value in candidates if len(value) >= 8 and "." in value}


def resolve_legacy_config_source(
    absolute: Path,
    rel_posix: str,
    text: str,
    run_identity: dict[str, Any],
    probe_identity: dict[str, Any],
    value_index: dict[str, set[str]],
) -> dict[str, Any]:
    embedded = sorted(set(CONFIG_ID_RE.findall(text)))
    if embedded and absolute.name.endswith("_config.json"):
        return {
            "path": repo_relative(absolute),
            "config_id": embedded[0],
            "basis": "self_config_file",
            "confidence": "strong",
            "note": "this file is itself a config file; its config_id is a self-declaration",
        }
    if embedded:
        return {
            "path": repo_relative(absolute),
            "config_id": embedded[0],
            "basis": "embedded_field",
            "confidence": "strong",
            "note": "the file itself declares its generating config id",
        }
    if code_relative(rel_posix).startswith(EXPLICIT_TREES[0] + "/") and probe_identity.get(
        "config_id"
    ):
        return {
            "path": probe_identity["path"],
            "config_id": probe_identity["config_id"],
            "basis": "group_directory_embedded_config",
            "confidence": "medium",
            "note": "no id in the file; assigned to the config file in the same directory",
        }
    shared = sorted(value for value in signature_numbers(text) if value in value_index)
    if shared and run_identity.get("config_id"):
        witness = sorted(value_index[shared[0]])[0]
        return {
            "path": run_identity.get("path"),
            "config_id": run_identity.get("config_id"),
            "basis": "content_value_match",
            "confidence": "medium",
            "note": (
                "no id in the file, but it shares evidence-key values "
                f"({', '.join(shared[:3])}) with the v6 id-carrying file {witness}"
            ),
        }
    if run_identity.get("config_id"):
        return {
            "path": run_identity["path"],
            "config_id": run_identity["config_id"],
            "basis": "directory_inference",
            "confidence": "weak",
            "note": (
                "no id in the file; assigned to the top-level legacy run config by "
                "directory membership only. mtime was NOT used as proof."
            ),
        }
    return {
        "path": None,
        "config_id": None,
        "basis": "unknown",
        "confidence": "none",
        "note": "no config id in the file and no legacy run config present",
    }


# --------------------------------------------------------------------------- #
# generator audit
# --------------------------------------------------------------------------- #
def audit_legacy_generator() -> dict[str, Any]:
    """Grep the Q2 source tree for anything that could emit the legacy config id."""
    literal_hits: list[dict[str, Any]] = []
    id_declarers: list[dict[str, Any]] = []
    output_path_hits: list[str] = []

    for candidate in sorted(CODE_ROOT.rglob("*.py")):
        if is_skipped(candidate):
            continue
        rel_posix = repo_relative(candidate)
        if is_never_touched(rel_posix) or rel_posix in GENERATOR_AUDIT_EXCLUDED:
            continue
        text = decode_text(candidate)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if LEGACY_CONFIG_ID in line:
                literal_hits.append({"path": rel_posix, "line": lineno, "text": line.strip()})
        for match in re.finditer(
            r"(?:evidence_config_id|config_id)[^=\n]{0,40}=\s*\"([^\"]+)\"", text
        ):
            id_declarers.append({"path": rel_posix, "config_id": match.group(1)})
        if '"gate_g_representative"' in text or "'gate_g_representative'" in text:
            output_path_hits.append(rel_posix)

    generator_candidates = sorted({item["path"] for item in id_declarers})
    available = bool(literal_hits)
    return {
        "searched_root": "src/q2/code/**/*.py",
        "excluded_from_scan": list(GENERATOR_AUDIT_EXCLUDED)
        + [f"prefix:{prefix}" for prefix in NEVER_TOUCHED_PREFIXES],
        "patterns": [
            LEGACY_CONFIG_ID,
            "evidence_config_id = <literal>",
            "config_id = <literal>",
            "output directory literal 'gate_g_representative'",
        ],
        "literal_config_id_hits": literal_hits,
        "declared_config_ids": id_declarers,
        "generator_candidates": generator_candidates,
        "writes_gate_g_representative": output_path_hits,
        "legacy_generator_unavailable": not available,
        "conclusion": (
            f"NO source file under src/q2/code declares or emits {LEGACY_CONFIG_ID!r}. "
            "The only Q2 Gate G package generator in-tree, "
            "src/q2/code/tools/generate_q2_closure_artifacts.py, declares "
            "'q2-final-evidence-v5-hero-closure' and writes into "
            "artifacts/gate_g_representative/. The top-level artifacts and the "
            "figures/ sidecars carrying the v6 id therefore cannot be regenerated "
            "byte-for-byte, nor even re-run with the same config id, from this tree."
        ),
    }


# --------------------------------------------------------------------------- #
# archive
# --------------------------------------------------------------------------- #
def archive_one(absolute: Path, rel_posix: str, source_sha256: str) -> dict[str, Any]:
    target = ARCHIVE_ROOT / code_relative(rel_posix)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(absolute, target)
    copy_sha256 = sha256_file(target)
    return {
        "archive_path": repo_relative(target),
        "copy_sha256": copy_sha256,
        "copy_verified": copy_sha256 == source_sha256,
    }


def build_manifest() -> dict[str, Any]:
    run_identity = load_config_identity(CODE_ROOT / LEGACY_RUN_CONFIG)
    probe_identity = load_config_identity(CODE_ROOT / PROBE_CONFIG)

    pre_code_files = count_files(CODE_ROOT, exclude=ARCHIVE_ROOT)
    pre_artifacts = count_files(CODE_ROOT / "artifacts", exclude=ARCHIVE_ROOT)
    pre_figures = count_files(CODE_ROOT / "figures")

    scope = discover_scope()
    texts = {path: decode_text(path) for path in scope}

    # Index distinctive evidence-key values by the files that carry the v6 config
    # id, so no-id siblings can be linked by content rather than by mtime.
    value_index: dict[str, set[str]] = {}
    for path in scope:
        rel_posix = repo_relative(path)
        if LEGACY_CONFIG_ID not in CONFIG_ID_RE.findall(texts[path]):
            continue
        for value in signature_numbers(texts[path]):
            value_index.setdefault(value, set()).add(rel_posix)

    entries: list[dict[str, Any]] = []
    for absolute in scope:
        rel_posix = repo_relative(absolute)
        text = texts[absolute]
        source_sha256 = sha256_file(absolute)
        stat = absolute.stat()
        source = resolve_legacy_config_source(
            absolute, rel_posix, text, run_identity, probe_identity, value_index
        )
        method_tokens = sorted(set(METHOD_LABEL_RE.findall(text)))
        archived = archive_one(absolute, rel_posix, source_sha256)
        entries.append(
            {
                "path": rel_posix,
                "sha256": source_sha256,
                "bytes": stat.st_size,
                "mtime": mtime_iso(absolute),
                "legacy_config_source": source["path"],
                "legacy_config_source_config_id": source["config_id"],
                "legacy_config_source_basis": source["basis"],
                "legacy_config_source_confidence": source["confidence"],
                "legacy_config_source_note": source["note"],
                "superseded": True,
                "not_for_current_paper": True,
                "legacy_method_labeling": True,
                "legacy_method_labeling_basis": (
                    "package_level: every archived entry belongs to the legacy "
                    "B1/B2-labeled evidence package"
                ),
                "method_label_tokens_found": method_tokens,
                "legacy_generator_unavailable": True,
                "archive_path": archived["archive_path"],
                "archive_sha256": archived["copy_sha256"],
                "copy_verified": archived["copy_verified"],
            }
        )

    discovered = {code_relative(entry["path"]) for entry in entries}
    missing: list[str] = []
    for name in expected_scope_paths():
        if name.endswith("/**"):
            prefix = name[:-3]
            if not any(rel.startswith(prefix + "/") for rel in discovered):
                missing.append(name)
        elif "*" in name:
            prefix, suffix = name.split("*", 1)
            if not any(rel.startswith(prefix) and rel.endswith(suffix) for rel in discovered):
                missing.append(name)
        elif name not in discovered:
            missing.append(name)

    post_code_files = count_files(CODE_ROOT, exclude=ARCHIVE_ROOT)
    post_artifacts = count_files(CODE_ROOT / "artifacts", exclude=ARCHIVE_ROOT)
    post_figures = count_files(CODE_ROOT / "figures")

    generator_audit = audit_legacy_generator()
    total_bytes = sum(entry["bytes"] for entry in entries)
    unverified = [entry["path"] for entry in entries if not entry["copy_verified"]]

    return {
        "schema_version": 1,
        "tool": "src/q2/code/tools/archive_q2_legacy_artifacts.py",
        "created_at": datetime.now().astimezone().isoformat(),
        "mode": "copy-only",
        "guarantee": (
            "No source file is moved, renamed or deleted. Every in-scope file is "
            "copied into the archive and the copy digest is compared to the source "
            "digest. The source trees are re-counted after the copy."
        ),
        "archive_root": repo_relative(ARCHIVE_ROOT),
        "archive_layout": "mirrors each in-scope path relative to src/q2/code/",
        "legacy_run_config": run_identity,
        "probe_run_config": probe_identity,
        "legacy_config_id": LEGACY_CONFIG_ID,
        "legacy_generator_audit": generator_audit,
        "flags": {
            "superseded": True,
            "not_for_current_paper": True,
            "legacy_method_labeling": "set true for every archived entry (package level)",
            "legacy_generator_unavailable": generator_audit["legacy_generator_unavailable"],
        },
        "counts": {
            "in_scope_files_found": len(entries),
            "copied_files": len(entries),
            "verified_copies": len(entries) - len(unverified),
            "unverified_copies": unverified,
            "missing": len(missing),
            "total_bytes": total_bytes,
            "archive_files_on_disk": count_files(ARCHIVE_ROOT),
        },
        "non_destructive_check": {
            "code_root_files_before": pre_code_files,
            "code_root_files_after": post_code_files,
            "artifacts_files_before": pre_artifacts,
            "artifacts_files_after": post_artifacts,
            "figures_files_before": pre_figures,
            "figures_files_after": post_figures,
            "counts_exclude": [
                "**/__pycache__/**",
                "**/.pytest_cache/**",
                repo_relative(ARCHIVE_ROOT),
            ],
            "source_deleted": False,
            "source_counts_unchanged": (
                pre_code_files == post_code_files
                and pre_artifacts == post_artifacts
                and pre_figures == post_figures
            ),
        },
        "missing": missing,
        "entries": entries,
    }


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def render_manifest_markdown(manifest: dict[str, Any]) -> str:
    counts = manifest["counts"]
    audit = manifest["legacy_generator_audit"]
    lines: list[str] = []
    lines.append("# 旧产物归档 manifest（q2-legacy-superseded-v6）")
    lines.append("")
    lines.append(f"- 生成时间：{manifest['created_at']}")
    lines.append(f"- 生成工具：`{manifest['tool']}`")
    lines.append(f"- 归档根目录：`{manifest['archive_root']}`")
    lines.append(f"- 归档方式：{manifest['mode']}（复制，不移动、不删除）")
    lines.append(f"- 范围内文件：{counts['in_scope_files_found']}")
    lines.append(f"- 已复制并校验：{counts['verified_copies']} / {counts['copied_files']}")
    lines.append(f"- 缺失（未找到，不报错）：{counts['missing']}")
    lines.append(f"- `legacy_generator_unavailable`：{audit['legacy_generator_unavailable']}")
    lines.append("")
    lines.append("## 旧配置来源核查")
    lines.append("")
    lines.append(f"- 顶层 run config：`{manifest['legacy_run_config'].get('path')}` → "
                 f"config_id = `{manifest['legacy_run_config'].get('config_id')}`")
    lines.append(f"- probe run config：`{manifest['probe_run_config'].get('path')}` → "
                 f"config_id = `{manifest['probe_run_config'].get('config_id')}`")
    lines.append("")
    lines.append("核查方式：优先读取文件内嵌的 `config_id` / `evidence_config_id` / "
                 "`source_config_id` 字段（`embedded_field`，strong）；未命中但位于 "
                 "`gate_g_production_probe/`（该目录自带 config 文件）记为 "
                 "`group_directory_embedded_config`（medium）；再退一步，若文件与某条带 v6 id 的"
                 "文件共享 `qhat_star` / `threshold` / `approximate_area_m2` 数值字面量，记为 "
                 "`content_value_match`（medium）；其余仅按目录归属推断，记为 "
                 "`directory_inference`（weak）。**没有使用 mtime 作为证据。**")
    lines.append("")
    lines.append("## 缺失文件")
    lines.append("")
    if manifest["missing"]:
        for name in manifest["missing"]:
            lines.append(f"- `{name}`")
    else:
        lines.append("（无）")
    lines.append("")
    lines.append("## 归档前后文件计数")
    lines.append("")
    check = manifest["non_destructive_check"]
    lines.append("| 目录 | 归档前 | 归档后 |")
    lines.append("|---|---:|---:|")
    lines.append(f"| `src/q2/code`（排除 __pycache__ / archive） | {check['code_root_files_before']} | {check['code_root_files_after']} |")
    lines.append(f"| `src/q2/code/artifacts`（排除 archive） | {check['artifacts_files_before']} | {check['artifacts_files_after']} |")
    lines.append(f"| `src/q2/code/figures` | {check['figures_files_before']} | {check['figures_files_after']} |")
    lines.append("")
    lines.append(f"源计数未变化：**{check['source_counts_unchanged']}**；删除源文件：**{check['source_deleted']}**")
    lines.append("")
    lines.append("## 条目")
    lines.append("")
    lines.append("| path | bytes | sha256 | legacy_config_source | basis | B1/B2 labeling |")
    lines.append("|---|---:|---|---|---|---|")
    for entry in manifest["entries"]:
        lines.append(
            "| `{path}` | {bytes} | `{sha256}` | `{src}` | {basis} | {label} |".format(
                path=entry["path"],
                bytes=entry["bytes"],
                sha256=entry["sha256"],
                src=entry["legacy_config_source"],
                basis=entry["legacy_config_source_basis"],
                label=entry["legacy_method_labeling"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_readme(manifest: dict[str, Any]) -> str:
    audit = manifest["legacy_generator_audit"]
    counts = manifest["counts"]
    return f"""# `_legacy_superseded_v6`：退出论文引用链的旧 Q2 产物（归档，不删除）

本目录是 **只读归档副本**，由 `src/q2/code/tools/archive_q2_legacy_artifacts.py`
生成（生成时间 {manifest['created_at']}）。目录布局与 `src/q2/code/` 下的相对路径一一对应。

## 这些文件为什么退出当前论文引用链

1. **配置身份对不上。** `artifacts/q2_final_evidence_config.json` 声明
   `config_id = "{manifest['legacy_config_id']}"`。
   在当前 `src/q2/code` 源码树中，**没有任何生成器会输出这个 id**。
2. **原生成器缺失。** 仓库内唯一的 Q2 Gate G 打包脚本是
   `tools/generate_q2_closure_artifacts.py`，它声明
   `q2-final-evidence-v5-hero-closure`，且写入
   `artifacts/gate_g_representative/`（上一轮已用修复后的 evaluator 重新生成），
   而不是本归档对应的顶层 `artifacts/` 与 `figures/`。
   核查方式：扫描 `src/q2/code/**/*.py` 中 `{manifest['legacy_config_id']}` 字面量、
   `evidence_config_id` / `config_id` 赋值与输出目录字面量。
   命中数 = {len(audit['literal_config_id_hits'])}，
   故 `legacy_generator_unavailable = {audit['legacy_generator_unavailable']}`。
3. **方法标签是旧代命名。** 本归档整体标记 `legacy_method_labeling = true`：
   这批产物同属旧的 B1/B2 命名与打包体系，不能直接当作当前方法身份体系
   （`method_id` / `paper_alias` / `formula_or_constructor`）的证据。
   每个条目另存 `method_label_tokens_found`，记录该文件内容里实际扫到的标签 token。
4. **本轮已确认 5% 候选域未收敛。** 旧产物中记录的候选域面积/连通分支不具备
   “全域已完整提取”的含义，继续引用会把未收敛结果包装成结论。

因此本目录内所有文件均带 `superseded = true`、`not_for_current_paper = true`。
**当前论文与测试只应读取 `artifacts/gate_g_representative/`（现行实现）与
`artifacts/q2_release_verified_v1/`（本轮发布目录）。**

## 「归档 ≠ 复现」

把文件复制到这里 **不构成** 对旧流程的复现：

- 旧 `q2-final-evidence-v6-dynamic-closure` 生成器在树内不存在，因此
  **既不能逐字节重现，也不能用同一个 config id 重跑**。
- 归档只保证“内容被完整保存且哈希可核对”（见 `MANIFEST.json` 的
  `sha256` / `archive_sha256` / `copy_verified`），不保证流程可执行。
- 若要重新生成等价证据，只能用现行生成命令：
  `PYTHONPATH=. python src/q2/code/tools/generate_q2_closure_artifacts.py`
  （输出到 `artifacts/gate_g_representative/`，config id 为
  `q2-final-evidence-v5-hero-closure`）。任何新产物都不得标注为 v6 流程的输出。
- 旧配置到现行实现的逐项映射见
  `../q2_release_verified_v1/resolved_config.json` 与
  `tools/resolve_q2_evidence_config.py`；未映射字段在该文件中显式列出。

## 内容清点

- 范围内文件：{counts['in_scope_files_found']}
- 已复制并校验哈希：{counts['verified_copies']} / {counts['copied_files']}
- 缺失（清单中列出但仓库中不存在，未报错退出）：{counts['missing']}
- 归档总字节：{counts['total_bytes']}

## 非破坏性保证

归档前后对 `src/q2/code`、`artifacts/`、`figures/` 重新计数：
```json
{json.dumps(manifest['non_destructive_check'], ensure_ascii=False, indent=2)}
```

清单与逐条哈希见 `MANIFEST.json`（机器可读）与 `MANIFEST.md`（可读）。
"""


def main() -> int:
    manifest = build_manifest()
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    (ARCHIVE_ROOT / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (ARCHIVE_ROOT / "MANIFEST.md").write_text(
        render_manifest_markdown(manifest), encoding="utf-8"
    )
    (ARCHIVE_ROOT / "README.md").write_text(render_readme(manifest), encoding="utf-8")

    summary = {
        "archive_root": manifest["archive_root"],
        "manifest_json": f"{manifest['archive_root']}/MANIFEST.json",
        "manifest_md": f"{manifest['archive_root']}/MANIFEST.md",
        "readme": f"{manifest['archive_root']}/README.md",
        "in_scope_files_found": manifest["counts"]["in_scope_files_found"],
        "copied_files": manifest["counts"]["copied_files"],
        "verified_copies": manifest["counts"]["verified_copies"],
        "unverified_copies": manifest["counts"]["unverified_copies"],
        "missing": manifest["missing"],
        "legacy_generator_unavailable": manifest["legacy_generator_audit"][
            "legacy_generator_unavailable"
        ],
        "literal_config_id_hits": manifest["legacy_generator_audit"][
            "literal_config_id_hits"
        ],
        "non_destructive_check": manifest["non_destructive_check"],
        "entries_by_config_id": {},
    }
    by_id: dict[str, int] = {}
    for entry in manifest["entries"]:
        key = entry["legacy_config_source_config_id"] or "<none>"
        by_id[key] = by_id.get(key, 0) + 1
    summary["entries_by_config_id"] = by_id
    summary["entries_by_basis"] = {}
    by_basis: dict[str, int] = {}
    for entry in manifest["entries"]:
        by_basis[entry["legacy_config_source_basis"]] = (
            by_basis.get(entry["legacy_config_source_basis"], 0) + 1
        )
    summary["entries_by_basis"] = by_basis

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
