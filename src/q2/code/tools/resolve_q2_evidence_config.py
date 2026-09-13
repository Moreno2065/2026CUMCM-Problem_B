"""Resolve the legacy Q2 evidence config onto the current implementation's configs.

``artifacts/q2_final_evidence_config.json`` carries
``config_id = "q2-final-evidence-v6-dynamic-closure"``.  No generator for that id
exists in this tree (see ``tools/archive_q2_legacy_artifacts.py``), so the file
cannot be replayed as-is.  This tool instead performs an explicit, auditable
translation of every field it can support onto the dataclasses the current code
actually consumes:

* ``solver/gate_g.py::GateGConfig``
* ``solver/outer_search.py::OuterSearchConfig``
* ``solver/candidate_regions.py::CandidateRegionConfig``

Rules:

* every source leaf path is either listed in ``mapped_fields`` or in
  ``unmapped_fields`` -- nothing is dropped silently;
* fields the current classes have but the legacy config never set are listed in
  ``defaulted_target_fields``;
* every field is classified as ``scientific_model_parameters`` /
  ``search_budget`` / ``extraction_budget`` / ``plotting_only``;
* the resolved config is validated by actually constructing the current
  dataclasses, so an unsupported value fails loudly instead of being copied;
* the legacy ``config_id`` is **not** copied into
  ``GateGConfig.evidence_config_id``: doing so would relabel fresh output as the
  missing v6 flow.  The current generator's id is used instead.

Usage::

    PYTHONPATH=. python src/q2/code/tools/resolve_q2_evidence_config.py
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

TOOL_PATH = Path(__file__).resolve()
CODE_ROOT = TOOL_PATH.parents[1]
REPO_ROOT = CODE_ROOT.parents[2]

SOURCE_CONFIG = Path("artifacts/q2_final_evidence_config.json")
SOLVER_CONFIG = Path("artifacts/q2_solver_config.json")
OUTPUT_DIR = Path("artifacts/q2_release_verified_v1")
OUTPUT_NAME = "resolved_config.json"

GENERATOR = "tools/generate_q2_closure_artifacts.py"
GENERATOR_OUTPUT_DIR = "artifacts/gate_g_representative"
CURRENT_EVIDENCE_CONFIG_ID = "q2-final-evidence-v5-hero-closure"

FINGERPRINTED_SOURCES = (
    "solver/gate_g.py",
    "solver/outer_search.py",
    "solver/candidate_regions.py",
    GENERATOR,
)

SKIP_PARTS = ("__pycache__", ".pytest_cache")

CONFIG_ID_RE = re.compile(
    r'"(?:config_id|evidence_config_id|source_config_id)"\s*:\s*"([^"]*)"'
)

#: (source dotted path, target class, target field, parameter class, note)
FIELD_MAP: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "outer_search_config.coarse_resolution",
        "OuterSearchConfig",
        "coarse_resolution",
        "search_budget",
        "coarse grid resolution of the deterministic outer search",
    ),
    (
        "outer_search_config.subdivision_depth",
        "OuterSearchConfig",
        "subdivision_depth",
        "search_budget",
        "subdivision depth of the outer search",
    ),
    (
        "outer_search_config.local_iterations",
        "OuterSearchConfig",
        "local_iterations",
        "search_budget",
        "fixed-direction local refinement iterations",
    ),
    (
        "outer_search_config.parallel_workers",
        "OuterSearchConfig",
        "parallel_workers",
        "search_budget",
        "worker count of the outer search",
    ),
    (
        "candidate_region_config.base_resolution",
        "CandidateRegionConfig",
        "base_resolution",
        "extraction_budget",
        "coarse base grid of the candidate-region extraction",
    ),
    (
        "candidate_region_config.max_refinement_depth",
        "CandidateRegionConfig",
        "max_refinement_depth",
        "extraction_budget",
        "maximum adaptive refinement depth",
    ),
    (
        "candidate_region_config.target_boundary_resolution_m",
        "CandidateRegionConfig",
        "target_boundary_resolution_m",
        "extraction_budget",
        "target (not achieved) boundary cell size in metres",
    ),
    (
        "candidate_region_config.near_hero_cell_factor",
        "CandidateRegionConfig",
        "near_hero_cell_factor",
        "extraction_budget",
        "near-hero refinement factor",
    ),
    (
        "candidate_region_config.max_refined_cells_per_level",
        "CandidateRegionConfig",
        "max_refined_cells_per_level",
        "extraction_budget",
        "per-level refinement cap; the round-2 under-resolution suspect",
    ),
    (
        "parallel_workers",
        "GateGConfig",
        "parallel_workers",
        "search_budget",
        "worker count of the Gate G package build",
    ),
    (
        "hero_promotion.tolerance_m",
        "GateGConfig",
        "hero_promotion_tolerance_m",
        "search_budget",
        "numerical tolerance used when promoting a closer Hero",
    ),
    (
        "hero_promotion.min_crec_margin_m",
        "GateGConfig",
        "hero_promotion_min_crec_margin_m",
        "search_budget",
        "minimum Crec margin required for a promotion",
    ),
    (
        "hero_promotion.max_rounds",
        "GateGConfig",
        "hero_promotion_max_rounds",
        "search_budget",
        "iteration budget of Hero promotion",
    ),
    (
        "hero_promotion.max_closure_rounds",
        "GateGConfig",
        "max_closure_rounds",
        "search_budget",
        "iteration budget of the closure loop",
    ),
    (
        "closure_seed_points",
        "GateGConfig",
        "closure_seed_points",
        "search_budget",
        "transformed: list[list[float]] -> tuple[Point2, ...]",
    ),
    (
        "gate_g_surface_config.legacy_surface_resolution",
        "GateGConfig",
        "surface_resolution",
        "extraction_budget",
        "legacy Gate G surface grid resolution",
    ),
    (
        "figure_dpi",
        "GateGConfig",
        "figure_dpi",
        "plotting_only",
        "figure resolution; no effect on any reported number",
    ),
    (
        "representative_case.S1",
        "build_gate_g_case",
        "S1",
        "scientific_model_parameters",
        "case anchor, passed positionally to build_gate_g_case",
    ),
    (
        "representative_case.theta1_deg",
        "build_gate_g_case",
        "theta1_deg",
        "scientific_model_parameters",
        "first-observation bearing of the representative case",
    ),
    (
        "representative_case.epsilon_deg",
        "build_gate_g_case",
        "epsilon_deg",
        "scientific_model_parameters",
        "angle-error bound epsilon; must agree with q2_solver_config.epsilon_deg",
    ),
)

UNMAPPED_REASONS: dict[str, tuple[str, str]] = {
    "config_id": (
        "provenance",
        "Legacy provenance id. Deliberately NOT copied into "
        "GateGConfig.evidence_config_id: the current generator declares "
        f"{CURRENT_EVIDENCE_CONFIG_ID!r}, and reusing the v6 id would relabel fresh "
        "output as the missing v6 flow.",
    ),
    "gate_g_surface_config.adaptive_surface": (
        "extraction_budget",
        "No toggle exists in the current implementation; adaptive candidate-region "
        "extraction is unconditionally enabled. Recorded, not consumed.",
    ),
    "representative_case.case_label": (
        "plotting_only",
        "Human-readable case label; not a solver parameter.",
    ),
}

#: Model constants that the evidence config does not carry at all.
SCIENTIFIC_PARAMETERS_ELSEWHERE = (
    "epsilon_deg",
    "omega_center_m",
    "omega_radius_m",
    "radial_interval_m",
    "near_distance_m",
    "reception_radius_m",
    "admissibility_multiplier",
    "inner_candidate_families",
)


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def code_relative(rel_posix: str) -> str:
    marker = "/src/q2/code/"
    if marker in rel_posix:
        return rel_posix.split(marker, 1)[1]
    prefix = "src/q2/code/"
    return rel_posix[len(prefix):] if rel_posix.startswith(prefix) else rel_posix


def leaf_paths(node: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Every scalar leaf plus every empty container, as ``(dotted path, value)``."""
    if isinstance(node, Mapping):
        if not node:
            return [(prefix, {})]
        collected: list[tuple[str, Any]] = []
        for key, value in node.items():
            collected.extend(leaf_paths(value, f"{prefix}.{key}" if prefix else str(key)))
        return collected
    if isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
        if not node:
            return [(prefix, [])]
        if all(not isinstance(item, (Mapping, list, tuple)) for item in node):
            return [(prefix, list(node))]
        collected = []
        for index, item in enumerate(node):
            collected.extend(leaf_paths(item, f"{prefix}[{index}]"))
        return collected
    return [(prefix, node)]


def get_dotted(source: Mapping[str, Any], dotted: str) -> Any:
    node: Any = source
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise KeyError(dotted)
        node = node[part]
    return node


# --------------------------------------------------------------------------- #
# generator audit (mirrors tools/archive_q2_legacy_artifacts.py)
# --------------------------------------------------------------------------- #
def audit_legacy_generator() -> dict[str, Any]:
    legacy_id = "q2-final-evidence-" + "v6-dynamic-closure"
    excluded = {
        "src/q2/code/tools/archive_q2_legacy_artifacts.py",
        "src/q2/code/tools/resolve_q2_evidence_config.py",
    }
    literal_hits: list[dict[str, Any]] = []
    declarers: list[dict[str, Any]] = []
    for candidate in sorted(CODE_ROOT.rglob("*.py")):
        if any(part in SKIP_PARTS for part in candidate.parts):
            continue
        rel_posix = repo_relative(candidate)
        if rel_posix in excluded:
            continue
        text = decode_text(candidate)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if legacy_id in line:
                literal_hits.append({"path": rel_posix, "line": lineno, "text": line.strip()})
        for match in re.finditer(
            r"(?:evidence_config_id|config_id)[^=\n]{0,40}=\s*\"([^\"]+)\"", text
        ):
            declarers.append({"path": rel_posix, "config_id": match.group(1)})
    return {
        "searched_root": "src/q2/code/**/*.py",
        "legacy_config_id": legacy_id,
        "literal_config_id_hits": literal_hits,
        "declared_config_ids": declarers,
        "legacy_generator_unavailable": not literal_hits,
        "conclusion": (
            f"No source file under src/q2/code emits {legacy_id!r}; the in-tree "
            f"Gate G package generator declares {CURRENT_EVIDENCE_CONFIG_ID!r}."
        ),
    }


# --------------------------------------------------------------------------- #
# mapping
# --------------------------------------------------------------------------- #
def build_mapping(source: Mapping[str, Any]) -> dict[str, Any]:
    consumed: set[str] = set()
    mapped_fields: list[dict[str, Any]] = []
    missing_source_fields: list[str] = []
    outer_kwargs: dict[str, Any] = {}
    candidate_kwargs: dict[str, Any] = {}
    gate_kwargs: dict[str, Any] = {}
    case_kwargs: dict[str, Any] = {}

    for dotted, target_class, target_field, parameter_class, note in FIELD_MAP:
        try:
            value = get_dotted(source, dotted)
        except KeyError:
            missing_source_fields.append(dotted)
            continue
        consumed.add(dotted)
        resolved_value: Any = value
        if target_class == "OuterSearchConfig":
            outer_kwargs[target_field] = value
        elif target_class == "CandidateRegionConfig":
            candidate_kwargs[target_field] = value
        elif target_class == "GateGConfig":
            if dotted == "closure_seed_points":
                resolved_value = [[float(point[0]), float(point[1])] for point in value]
            gate_kwargs[target_field] = value
        elif target_class == "build_gate_g_case":
            case_kwargs[target_field] = value
        mapped_fields.append(
            {
                "source_path": dotted,
                "source_value": value,
                "target_class": target_class,
                "target_field": target_field,
                "resolved_value": resolved_value,
                "parameter_class": parameter_class,
                "mapping": "transformed" if dotted == "closure_seed_points" else "direct",
                "note": note,
            }
        )

    source_leaves = dict(leaf_paths(source))
    unmapped_fields: list[dict[str, Any]] = []
    for path in sorted(source_leaves):
        if path in consumed:
            continue
        parameter_class, reason = UNMAPPED_REASONS.get(
            path, ("unclassified", "no corresponding field in the current implementation")
        )
        unmapped_fields.append(
            {
                "source_path": path,
                "source_value": source_leaves[path],
                "parameter_class": parameter_class,
                "reason": reason,
            }
        )

    return {
        "mapped_fields": mapped_fields,
        "unmapped_fields": unmapped_fields,
        "missing_source_fields": missing_source_fields,
        "outer_kwargs": outer_kwargs,
        "candidate_kwargs": candidate_kwargs,
        "gate_kwargs": gate_kwargs,
        "case_kwargs": case_kwargs,
    }


def defaulted_target_fields(candidate_kwargs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Target fields the legacy config never sets; the current default applies."""
    from src.q2.code.solver.candidate_regions import CandidateRegionConfig

    defaulted: list[dict[str, Any]] = []
    supplied = set(candidate_kwargs)
    for name in CandidateRegionConfig.__dataclass_fields__:
        if name in supplied:
            continue
        defaulted.append(
            {
                "target_class": "CandidateRegionConfig",
                "target_field": name,
                "current_default": CandidateRegionConfig.__dataclass_fields__[
                    name
                ].default,
                "source_status": "absent_from_legacy_config",
                "reason": (
                    "the legacy config never sets this field, so the current "
                    "implementation default applies"
                ),
            }
        )
    return defaulted


def classify(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    classes: dict[str, dict[str, Any]] = {
        "scientific_model_parameters": {
            "description": (
                "Physical/statistical quantities of the model. Changing them changes "
                "the scientific claim, not the resolution."
            ),
            "source_paths": [],
            "target_fields": [],
        },
        "search_budget": {
            "description": (
                "Outer-search and promotion budgets/tolerances. Changing them may "
                "change the incumbent but not the model."
            ),
            "source_paths": [],
            "target_fields": [],
        },
        "extraction_budget": {
            "description": (
                "Candidate-region extraction resolution/budget. Changing them changes "
                "only how finely the numerical region is resolved."
            ),
            "source_paths": [],
            "target_fields": [],
        },
        "plotting_only": {
            "description": "Affects rendering only; never a reported number.",
            "source_paths": [],
            "target_fields": [],
        },
    }
    for entry in entries:
        bucket = classes.get(entry["parameter_class"])
        if bucket is None:
            continue
        bucket["source_paths"].append(entry["source_path"])
        bucket["target_fields"].append(
            f"{entry['target_class']}.{entry['target_field']}"
        )
    return classes


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    source_path = CODE_ROOT / SOURCE_CONFIG
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()

    mapping = build_mapping(source)
    unmapped_fields = mapping["unmapped_fields"]
    all_classifiable = list(mapping["mapped_fields"]) + [
        {**entry, "target_class": "", "target_field": entry["source_path"]}
        for entry in unmapped_fields
    ]
    parameter_classes = classify(all_classifiable)

    validation_errors: list[str] = []
    resolved: dict[str, Any] = {}
    try:
        from src.q2.code.geometry.primitives import Point2
        from src.q2.code.solver.candidate_regions import CandidateRegionConfig
        from src.q2.code.solver.gate_g import GateGConfig
        from src.q2.code.solver.outer_search import OuterSearchConfig

        outer = OuterSearchConfig(**mapping["outer_kwargs"])
        candidate = CandidateRegionConfig(**mapping["candidate_kwargs"])
        raw_seed_points = mapping["gate_kwargs"].pop("closure_seed_points", ())
        seed_points = tuple(
            Point2(float(point[0]), float(point[1])) for point in raw_seed_points
        )
        gate = GateGConfig(
            outer_config=outer,
            candidate_region_config=candidate,
            evidence_config_id=CURRENT_EVIDENCE_CONFIG_ID,
            closure_seed_points=seed_points,
            **mapping["gate_kwargs"],
        )
        resolved = {
            "GateGConfig": {
                "outer_config": "see OuterSearchConfig",
                "candidate_region_config": "see CandidateRegionConfig",
                "evidence_config_id": gate.evidence_config_id,
                "evidence_config_id_note": (
                    "current generator id, NOT the legacy source_config_id"
                ),
                "surface_resolution": gate.surface_resolution,
                "figure_dpi": gate.figure_dpi,
                "parallel_workers": gate.parallel_workers,
                "hero_promotion_tolerance_m": gate.hero_promotion_tolerance_m,
                "hero_promotion_min_crec_margin_m": gate.hero_promotion_min_crec_margin_m,
                "hero_promotion_max_rounds": gate.hero_promotion_max_rounds,
                "max_closure_rounds": gate.max_closure_rounds,
                "closure_seed_points": [
                    [point.x, point.y] for point in gate.closure_seed_points
                ],
            },
            "OuterSearchConfig": {
                name: getattr(outer, name) for name in OuterSearchConfig.__dataclass_fields__
            },
            "CandidateRegionConfig": {
                name: getattr(candidate, name)
                for name in CandidateRegionConfig.__dataclass_fields__
            },
            "build_gate_g_case": {
                "S1": mapping["case_kwargs"].get("S1"),
                "theta1_deg": mapping["case_kwargs"].get("theta1_deg"),
                "epsilon_deg": mapping["case_kwargs"].get("epsilon_deg"),
            },
        }
    except Exception as exc:  # pragma: no cover - defensive: report, never hide
        validation_errors.append(f"{type(exc).__name__}: {exc}")

    defaulted = []
    if not validation_errors:
        try:
            defaulted = defaulted_target_fields(mapping["candidate_kwargs"])
        except Exception as exc:  # pragma: no cover
            validation_errors.append(f"defaulted-field probe failed: {exc}")

    source_fingerprints = {
        path: sha256_file(CODE_ROOT / path)
        for path in FINGERPRINTED_SOURCES
        if (CODE_ROOT / path).is_file()
    }
    solver_config = {}
    if (CODE_ROOT / SOLVER_CONFIG).is_file():
        solver_config = json.loads((CODE_ROOT / SOLVER_CONFIG).read_text(encoding="utf-8"))

    generator_audit = audit_legacy_generator()
    output_path = OUTPUT_DIR / OUTPUT_NAME
    record: dict[str, Any] = {
        "schema_version": 1,
        "tool": "src/q2/code/tools/resolve_q2_evidence_config.py",
        "generated_at": datetime.now().astimezone().isoformat(),
        "resolved_config_path": repo_relative(CODE_ROOT / output_path),
        "source_config_path": repo_relative(source_path),
        "source_config_id": source.get("config_id"),
        "source_config_sha256": source_sha256,
        "legacy_generator_unavailable": generator_audit["legacy_generator_unavailable"],
        "legacy_generator_audit": generator_audit,
        "current_implementation": {
            "evidence_config_id": CURRENT_EVIDENCE_CONFIG_ID,
            "evidence_config_id_declared_in": f"src/q2/code/{GENERATOR}",
            "package_output_dir": f"src/q2/code/{GENERATOR_OUTPUT_DIR}",
            "regeneration_command": (
                f"PYTHONPATH=. python src/q2/code/{GENERATOR}"
            ),
            "verification_command": (
                "cd /d/CUMCM2026 && python -m pytest src/q2/code/tests -q -p no:cacheprovider"
            ),
            "source_sha256": source_fingerprints,
        },
        "mapped_fields": mapping["mapped_fields"],
        "unmapped_fields": unmapped_fields,
        "defaulted_target_fields": defaulted,
        "parameter_classes": parameter_classes,
        "parameter_class_notes": [
            "hero_promotion.* are promotion/acceptance policy, not a pure budget; they "
            "are grouped under search_budget because the mandated four classes have no "
            "dedicated policy class. Iteration limits (max_rounds, max_closure_rounds) "
            "are budget-like; tolerance_m / min_crec_margin_m are numerical tolerances.",
            "unmapped entries keep their source-side class so a reader can see what the "
            "field would have been, even though nothing in the current code consumes it.",
        ],
        "resolved_config": resolved,
        "validation": {
            "constructs_current_config_classes": not validation_errors,
            "errors": validation_errors,
            "classes_constructed": [
                "src.q2.code.solver.gate_g.GateGConfig",
                "src.q2.code.solver.outer_search.OuterSearchConfig",
                "src.q2.code.solver.candidate_regions.CandidateRegionConfig",
            ],
        },
        "cross_reference": {
            "note": (
                "Scientific model constants are NOT carried by the evidence config; "
                "they live in the frozen solver config / model defaults. They are "
                "listed here read-only and are not part of mapped_fields."
            ),
            "frozen_solver_config_path": (
                repo_relative(CODE_ROOT / SOLVER_CONFIG)
                if (CODE_ROOT / SOLVER_CONFIG).is_file()
                else None
            ),
            "frozen_solver_config_id": solver_config.get("config_id"),
            "model_parameters_outside_source_config": {
                name: solver_config.get(name) for name in SCIENTIFIC_PARAMETERS_ELSEWHERE
            },
            "epsilon_deg_agreement": (
                solver_config.get("epsilon_deg")
                == mapping["case_kwargs"].get("epsilon_deg")
            ),
        },
        "reproduction_statement": {
            "byte_exact_reproduction_of_v6": False,
            "claim_forbidden": (
                "Do not claim that this resolved config reproduces the "
                "'q2-final-evidence-v6-dynamic-closure' flow byte-for-byte, or even "
                "re-runs it. That generator is absent from the repository."
            ),
            "what_is_provided_instead": (
                "A field-by-field mapping onto the current implementation, the explicit "
                "list of unmapped fields, and the command/version that regenerates a "
                "current, verifiable Q2 Gate G package."
            ),
            "regeneration_command": f"PYTHONPATH=. python src/q2/code/{GENERATOR}",
            "regeneration_output_dir": f"src/q2/code/{GENERATOR_OUTPUT_DIR}",
            "regeneration_config_id": CURRENT_EVIDENCE_CONFIG_ID,
            "implementation_version": (
                "content-addressed (no git in this repository): see "
                "current_implementation.source_sha256"
            ),
        },
    }

    destination = CODE_ROOT / output_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summary = {
        "resolved_config_path": record["resolved_config_path"],
        "source_config_id": record["source_config_id"],
        "source_config_sha256": record["source_config_sha256"],
        "legacy_generator_unavailable": record["legacy_generator_unavailable"],
        "mapped_field_count": len(record["mapped_fields"]),
        "unmapped_field_count": len(record["unmapped_fields"]),
        "unmapped_fields": [entry["source_path"] for entry in record["unmapped_fields"]],
        "defaulted_target_fields": [
            f"{entry['target_class']}.{entry['target_field']}" for entry in defaulted
        ],
        "validation": record["validation"],
        "parameter_classes": {
            name: len(bucket["source_paths"])
            for name, bucket in record["parameter_classes"].items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not validation_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
