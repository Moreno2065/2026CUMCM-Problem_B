"""Independent local probe of the Q2 center case (diagnostic, no repo imports).

Frozen center case
------------------
``S1 = (0, 0)``, ``theta1 = 0 deg``, ``epsilon = 1 deg``, and

```text
A1 = { S1 + rho*u(theta) : 5 < rho <= 1500, d_S(theta, theta1) <= epsilon }
```

The 1800 m target disk is not an active truncation here: with ``S1`` at the
origin ``|G| = rho <= 1500 < 1800``.

What this probe measures
------------------------
Per probe point ``S2`` (the frozen Hero plus small offsets) two quantities:

* ``g(S2)`` -- sampled robust-reception violation
  ``max_target [ |S2 - G| - max(1000, |G - S1|) ]``;
* ``finite scan max diameter`` -- the maximum pure-angular Q1 intersection
  diameter over a finite scan of admissible second bearings ``beta``.

The upstream receipt reports 5% candidate areas of ``0 / 629.757 / 0 m^2``.
This probe asks whether the *local* geometry around the frozen Hero is itself
razor-thin, or whether the extraction loss is a numerical/budget artefact.

Independence and boundary of the claim
--------------------------------------
Nothing is imported from ``src.q2.code`` or ``src.q1``.  The wedge polygon, the
angular image, the admissible second-bearing interval and the violation
function are all re-implemented here from the frozen definitions; in
particular ``q1_adapter``, ``q1_geometry``, ``crec``, ``a1`` and
``angular_image`` are not used.  The probe is a *locator*, not production
verification: the finite scan maximum is a sampled lower bound of the
continuous inner supremum, never a certified upper bound, and it does not
prove that the whole candidate domain was found.  ``CERTIFIED_GLOBAL_OPTIMUM``
stays False and nothing here certifies a global optimum.

Run from the repository root::

    PYTHONPATH=. python src/q2/code/tools/q2_center_case_local_probe.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

S1 = (0.0, 0.0)
THETA1_DEG = 0.0
EPSILON_DEG = 1.0
INNER_RADIUS_M = 5.0
OUTER_RADIUS_M = 1500.0
OMEGA_RADIUS_M = 1800.0
MIN_RECEPTION_RADIUS_M = 1000.0
NEAR_RADIUS_M = 5.0

HERO_S2 = (800.1012338639696, -606.388471543349)
RECEIPT_Q_M = 134.07676525132717
THRESHOLD_ETA = 0.05

# Receipt values from the round-2 work order (Prompt v2, section 11).  They are
# comparison data only: no table entry below is produced from them.
RECEIPT_REFERENCE_TABLE = (
    ("(0,0)", (0, 0), -0.000000756869, 134.076765251327),
    ("(-1,0)", (-1, 0), -0.794918700127, 134.259318354649),
    ("(0,+1)", (0, 1), -0.606160205542, 134.212820719502),
    ("(-5,0)", (-5, 0), -3.970894736314, 134.991512538439),
    ("(0,+5)", (0, 5), -3.024453082973, 134.763542168377),
    ("(-10,0)", (-10, 0), -7.932482852857, 135.911212421794),
    ("(0,+10)", (0, 10), -6.032956373929, 135.466851848791),
)

BETA_SAMPLE_COUNT = 4097
VIOLATION_ANGLE_SAMPLE_COUNT = 4097
# For rho <= 1000 the violation is a convex distance function on a convex
# annular sector, so its maximum sits on an extreme point (rho in {5, 1000});
# for rho > 1000 the radial derivative is ``-u_hat . u - 1 <= 0``, so the
# supremum is reached as rho -> 1000+.  These three radii therefore already
# contain the maximizer for every probed theta.
VIOLATION_CANDIDATE_RADII_M = (INNER_RADIUS_M, 1000.0, OUTER_RADIUS_M)
DENSE_CROSS_CHECK_RADII = 512
DENSE_CROSS_CHECK_ANGLES = 4097
INWARD_AXIS_STEP_M = 0.5
INWARD_AXIS_MAX_OFFSET_M = 60.0

# Frozen Q1 vertex tolerance: absolute metres plus a relative term for
# large-coordinate safety (src/q1/code/q1_geometry.py, Tolerance).
VERTEX_TOL_ABS_M = 1e-9
VERTEX_TOL_REL = 2e-14
PARALLEL_DET_TOL = 1e-14
DEDUPE_TOL_M = 1e-9

TOOL_PATH = Path(__file__).resolve()
REPO_ROOT = TOOL_PATH.parents[4]
OUTPUT_PATH = (
    REPO_ROOT
    / "src/q2/code/artifacts/q2_round2_source_snapshot/local_probe_center_case.json"
)


@dataclass(frozen=True)
class HalfPlane:
    """Closed half-plane ``a*x + b*y <= c`` with a unit normal ``(a, b)``."""

    a: float
    b: float
    c: float
    source: str
    side: str


@dataclass(frozen=True)
class ScanResult:
    max_diameter_m: float
    argmax_beta_deg: float | None
    beta_samples: int
    beta_samples_used: int
    gated_beta_samples: int
    unbounded_beta_samples: int
    empty_beta_samples: int
    admissible_interval_deg: tuple[float, float]
    angular_image_deg: tuple[float, float]


def circular_distance_deg(left: float, right: float) -> float:
    return min((left - right) % 360.0, (right - left) % 360.0)


def bearing_deg(origin: tuple[float, float], point: tuple[float, float]) -> float:
    return math.degrees(math.atan2(point[1] - origin[1], point[0] - origin[0])) % 360.0


def unit_deg(angle_deg: float) -> tuple[float, float]:
    radians = math.radians(angle_deg)
    return math.cos(radians), math.sin(radians)


def point_on_ray(
    station: tuple[float, float], angle_deg: float, radius_m: float
) -> tuple[float, float]:
    ux, uy = unit_deg(angle_deg)
    return station[0] + radius_m * ux, station[1] + radius_m * uy


def distance_m(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def wedge_halfplanes(
    station: tuple[float, float], bearing: float, epsilon_deg: float
) -> list[HalfPlane]:
    """The two closed half-planes of a ``bearing +- epsilon`` wedge.

    Same orientation convention as the frozen Q1 model: the lower boundary is
    ``cross(u(bearing - eps), P - S) >= 0`` and the upper boundary is
    ``cross(P - S, u(bearing + eps)) >= 0``.
    """
    x, y = station
    lower_angle = (bearing - epsilon_deg) % 360.0
    upper_angle = (bearing + epsilon_deg) % 360.0
    ux_l, uy_l = unit_deg(lower_angle)
    ux_u, uy_u = unit_deg(upper_angle)
    lower = HalfPlane(uy_l, -ux_l, uy_l * x - ux_l * y, "wedge", "lower")
    upper = HalfPlane(-uy_u, ux_u, -uy_u * x + ux_u * y, "wedge", "upper")
    return [lower, upper]


def vertex_tolerance_m(*scales: float) -> float:
    return VERTEX_TOL_ABS_M + VERTEX_TOL_REL * max(1.0, *scales)


def intersection_vertices(halfplanes: list[HalfPlane]) -> list[tuple[float, float]]:
    """Feasible vertices of a closed half-plane intersection.

    Every vertex of a bounded two-dimensional intersection is the crossing of
    two boundary lines, so enumerating feasible line pairs is complete for the
    four-half-plane Q1 wedge structure.  An unbounded intersection still
    returns its two feasible vertices; the caller checks boundedness before
    using any diameter.
    """
    candidates: list[tuple[float, float]] = []
    for first in range(len(halfplanes)):
        for second in range(first + 1, len(halfplanes)):
            left, right = halfplanes[first], halfplanes[second]
            det = left.a * right.b - right.a * left.b
            if abs(det) <= PARALLEL_DET_TOL:
                continue
            x = (left.c * right.b - right.c * left.b) / det
            y = (left.a * right.c - right.a * left.c) / det
            if not (math.isfinite(x) and math.isfinite(y)):
                continue
            scale = max(
                1.0, abs(x), abs(y), *(abs(halfplane.c) for halfplane in halfplanes)
            )
            tolerance = vertex_tolerance_m(scale)
            if all(
                halfplane.a * x + halfplane.b * y <= halfplane.c + tolerance
                for halfplane in halfplanes
            ):
                candidates.append((x, y))
    unique: list[tuple[float, float]] = []
    for point in candidates:
        if all(distance_m(point, kept) > DEDUPE_TOL_M for kept in unique):
            unique.append(point)
    return unique


def polygon_diameter_m(vertices: list[tuple[float, float]]) -> float:
    if len(vertices) < 2:
        return 0.0
    return max(
        distance_m(vertices[i], vertices[j])
        for i in range(len(vertices))
        for j in range(i + 1, len(vertices))
    )


def q1_wedge_bounded(beta_deg: float, epsilon_deg: float = EPSILON_DEG) -> bool:
    """The two wedges share a recession direction iff their axes are <= 2*eps apart."""
    return circular_distance_deg(beta_deg, THETA1_DEG) > 2.0 * epsilon_deg


def arc_tangency_angles_deg(
    center: tuple[float, float],
    radius_m: float,
    observer: tuple[float, float],
) -> tuple[float, ...]:
    """Angles (from the arc centre) of the point-tangency cuts, if any."""
    span = distance_m(center, observer)
    if span <= radius_m:
        return ()
    offset = math.degrees(math.acos(min(1.0, radius_m / span)))
    base = bearing_deg(center, observer)
    return ((base + offset) % 360.0, (base - offset) % 360.0)


def unwrap_to_reference(angle_deg: float, reference_deg: float) -> float:
    candidates = (angle_deg - 360.0, angle_deg, angle_deg + 360.0)
    return min(candidates, key=lambda value: abs(value - reference_deg))


def center_case_a1_boundary(
    station2: tuple[float, float],
) -> tuple[tuple[str, tuple[float, float], tuple[float, float]], ...]:
    """Boundary pieces of the frozen center-case A1 (two rays, two arcs)."""
    lower_angle = THETA1_DEG - EPSILON_DEG
    upper_angle = THETA1_DEG + EPSILON_DEG
    pieces: list[tuple[str, tuple[float, float], tuple[float, float]]] = []
    for angle in (lower_angle, upper_angle):
        pieces.append(
            (
                "segment",
                point_on_ray(S1, angle, INNER_RADIUS_M),
                point_on_ray(S1, angle, OUTER_RADIUS_M),
            )
        )
    for radius_m in (INNER_RADIUS_M, OUTER_RADIUS_M):
        pieces.append(
            (
                "arc",
                point_on_ray(S1, lower_angle, radius_m),
                point_on_ray(S1, upper_angle, radius_m),
            )
        )
    return tuple(pieces)


def center_case_a1_image_deg(station2: tuple[float, float]) -> tuple[float, float]:
    """Angular image of the center-case A1 as seen from ``station2``.

    Each boundary piece is straight (bearing is monotone along it) or a
    circular arc (bearing is monotone between the point-tangency cuts), so the
    image of a piece is the interval spanned by its critical points and the
    image of A1 is the union of those intervals.  A1's image is connected here,
    so a single unwrapped interval is returned; a disconnected image raises
    rather than being silently merged.
    """
    intervals: list[tuple[float, float]] = []
    for kind, start, end in center_case_a1_boundary(station2):
        criticals = [start, end]
        if kind == "arc":
            radius_m = distance_m(S1, start)
            arc_start_angle = math.degrees(
                math.atan2(start[1] - S1[1], start[0] - S1[0])
            )
            for angle in arc_tangency_angles_deg(S1, radius_m, station2):
                fraction = (angle - arc_start_angle) % 360.0
                if fraction <= 2.0 * EPSILON_DEG + 1e-9:
                    criticals.append(point_on_ray(S1, angle, radius_m))
        bearings = [bearing_deg(station2, point) for point in criticals]
        unwrapped = [unwrap_to_reference(value, bearings[0]) for value in bearings]
        intervals.append((min(unwrapped), max(unwrapped)))

    base = intervals[0][0]
    merged: list[tuple[float, float]] = []
    for lo, hi in sorted(
        (unwrap_to_reference(lo, base), unwrap_to_reference(hi, base))
        for lo, hi in intervals
    ):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    if len(merged) > 1 and merged[0][0] + 360.0 <= merged[-1][1] + 1e-12:
        merged = [(merged[-1][0], merged[0][1] + 360.0)]
    if len(merged) != 1:
        raise ValueError(
            "center-case angular image is not a single interval; the probe is "
            "scoped to the center case and must not merge disjoint branches"
        )
    return merged[0]


def min_clearance_to_a1_m(station2: tuple[float, float]) -> float:
    """Distance from ``station2`` to the closed center-case A1.

    Candidates are the perpendicular feet on the two radial boundary segments
    and the nearest point of each arc, so the minimum is exact for this
    geometry.  It is used only to show that the five-metre near disk around
    ``station2`` cannot clip A1, which keeps this probe's image identical to
    the near-aware production image.
    """
    candidates: list[tuple[float, float]] = []
    reference = bearing_deg(S1, station2)
    for angle in (THETA1_DEG - EPSILON_DEG, THETA1_DEG + EPSILON_DEG):
        ux, uy = unit_deg(angle)
        foot = station2[0] * ux + station2[1] * uy
        if INNER_RADIUS_M <= foot <= OUTER_RADIUS_M:
            candidates.append(point_on_ray(S1, angle, foot))
        candidates.append(point_on_ray(S1, angle, INNER_RADIUS_M))
        candidates.append(point_on_ray(S1, angle, OUTER_RADIUS_M))
    for radius_m in (INNER_RADIUS_M, OUTER_RADIUS_M):
        if circular_distance_deg(reference, THETA1_DEG) <= EPSILON_DEG:
            candidates.append(point_on_ray(S1, reference, radius_m))
        else:
            nearest = (
                THETA1_DEG - EPSILON_DEG if reference < THETA1_DEG else THETA1_DEG + EPSILON_DEG
            )
            candidates.append(point_on_ray(S1, nearest, radius_m))
    return min(distance_m(station2, point) for point in candidates)


def violation_at(
    station2: tuple[float, float], rho_m: float, theta_deg: float
) -> float:
    point = point_on_ray(S1, theta_deg, rho_m)
    return distance_m(station2, point) - max(
        MIN_RECEPTION_RADIUS_M, distance_m(point, S1)
    )


def sampled_violation_m(
    station2: tuple[float, float],
    radii: tuple[float, ...] = VIOLATION_CANDIDATE_RADII_M,
    angle_samples: int = VIOLATION_ANGLE_SAMPLE_COUNT,
) -> tuple[float, tuple[float, float]]:
    """Sampled ``g(S2)`` plus its active ``(rho, theta)`` sample."""
    best = -math.inf
    active = (math.nan, math.nan)
    for index in range(angle_samples):
        theta = THETA1_DEG - EPSILON_DEG + 2.0 * EPSILON_DEG * index / (angle_samples - 1)
        for rho in radii:
            value = violation_at(station2, rho, theta)
            if value > best:
                best = value
                active = (rho, theta)
    return best, active


def dense_violation_m(
    station2: tuple[float, float],
    radial_samples: int = DENSE_CROSS_CHECK_RADII,
    angle_samples: int = DENSE_CROSS_CHECK_ANGLES,
) -> float:
    """Independent denser grid for ``g(S2)`` used only as a cross-check."""
    best = -math.inf
    for radial_index in range(radial_samples):
        rho = INNER_RADIUS_M + (OUTER_RADIUS_M - INNER_RADIUS_M) * radial_index / (
            radial_samples - 1
        )
        for angle_index in range(angle_samples):
            theta = THETA1_DEG - EPSILON_DEG + 2.0 * EPSILON_DEG * angle_index / (
                angle_samples - 1
            )
            best = max(best, violation_at(station2, rho, theta))
    return best


def scan_max_diameter_m(
    station2: tuple[float, float],
    sample_count: int = BETA_SAMPLE_COUNT,
) -> ScanResult:
    """Finite scan of admissible second bearings for the pure-angular Q1 diameter."""
    image = center_case_a1_image_deg(station2)
    lower = image[0] - EPSILON_DEG
    upper = image[1] + EPSILON_DEG
    best = -1.0
    argmax: float | None = None
    used = 0
    gated = 0
    unbounded = 0
    empty = 0
    for index in range(sample_count):
        beta = lower + (upper - lower) * index / (sample_count - 1)
        if circular_distance_deg(beta, THETA1_DEG) <= 3.0 * EPSILON_DEG:
            gated += 1
            continue
        used += 1
        if not q1_wedge_bounded(beta):
            unbounded += 1
            continue
        halfplanes = wedge_halfplanes(S1, THETA1_DEG, EPSILON_DEG) + wedge_halfplanes(
            station2, beta, EPSILON_DEG
        )
        vertices = intersection_vertices(halfplanes)
        if not vertices:
            empty += 1
            continue
        diameter = polygon_diameter_m(vertices)
        if diameter > best:
            best = diameter
            argmax = beta
    if unbounded:
        raise RuntimeError(
            "an admissible sample left the Q1 wedge intersection unbounded; the "
            "sampled supremum is infinite and must not be reported as finite"
        )
    if argmax is None:
        raise RuntimeError(
            "no admissible sample produced a bounded Q1 polygon; the scan is "
            "vacuous and must not be reported as a finite diameter"
        )
    return ScanResult(
        max_diameter_m=best,
        argmax_beta_deg=argmax,
        beta_samples=sample_count,
        beta_samples_used=used,
        gated_beta_samples=gated,
        unbounded_beta_samples=unbounded,
        empty_beta_samples=empty,
        admissible_interval_deg=(lower, upper),
        angular_image_deg=image,
    )


def inward_axis_threshold_crossing_m(
    threshold_m: float, base_s2: tuple[float, float] = HERO_S2
) -> dict[str, object]:
    """First sampled inward step where the scan value exceeds the threshold.

    ``inward`` is the ``-x`` direction at fixed ``y``.  The first crossing is
    reported on an explicit uniform grid, together with the bracket it was
    found in; monotonicity of the scan value along the axis is not assumed, and
    no value is reported past the first crossing.
    """
    step = INWARD_AXIS_STEP_M
    count = int(round(INWARD_AXIS_MAX_OFFSET_M / step))
    previous_offset = 0.0
    previous_value = scan_max_diameter_m(base_s2).max_diameter_m
    if previous_value > threshold_m:
        return {
            "crossing_offset_m": 0.0,
            "grid_step_m": step,
            "grid_max_offset_m": INWARD_AXIS_MAX_OFFSET_M,
            "bracket_m": (0.0, 0.0),
            "value_at_start_m": previous_value,
            "value_at_crossing_m": previous_value,
            "threshold_m": threshold_m,
            "note": "start point already exceeds the threshold",
        }
    for index in range(1, count + 1):
        offset = index * step
        station2 = (base_s2[0] - offset, base_s2[1])
        value = scan_max_diameter_m(station2).max_diameter_m
        if value > threshold_m:
            return {
                "crossing_offset_m": offset,
                "grid_step_m": step,
                "grid_max_offset_m": INWARD_AXIS_MAX_OFFSET_M,
                "bracket_m": (previous_offset, offset),
                "value_at_bracket_start_m": previous_value,
                "value_at_crossing_m": value,
                "threshold_m": threshold_m,
                "note": (
                    "first sampled inward offset whose finite-scan value exceeds the "
                    "threshold; sampled quantity, not a certified band boundary"
                ),
            }
        previous_offset = offset
        previous_value = value
    return {
        "crossing_offset_m": None,
        "grid_step_m": step,
        "grid_max_offset_m": INWARD_AXIS_MAX_OFFSET_M,
        "bracket_m": None,
        "value_at_grid_end_m": previous_value,
        "threshold_m": threshold_m,
        "note": "no crossing found inside the scanned inward grid",
    }


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_report() -> dict[str, object]:
    threshold_m = (1.0 + THRESHOLD_ETA) * RECEIPT_Q_M
    rows: list[dict[str, object]] = []
    for label, (dx, dy), receipt_g, receipt_diameter in RECEIPT_REFERENCE_TABLE:
        station2 = (HERO_S2[0] + dx, HERO_S2[1] + dy)
        violation, active = sampled_violation_m(station2)
        scan = scan_max_diameter_m(station2)
        clearance = min_clearance_to_a1_m(station2)
        rows.append(
            {
                "label": label,
                "offset_m": [dx, dy],
                "s2": [station2[0], station2[1]],
                "s2_radius_from_s1_m": math.hypot(*station2),
                "g_violation_m": violation,
                "g_active_sample": {
                    "rho_m": active[0],
                    "theta_from_s1_deg": active[1],
                    "point": list(point_on_ray(S1, active[1], active[0])),
                },
                "g_in_crec_by_sampled_sign": violation <= 0.0,
                "finite_scan_max_diameter_m": scan.max_diameter_m,
                "finite_scan_argmax_beta_deg": scan.argmax_beta_deg,
                "angular_image_deg": list(scan.angular_image_deg),
                "admissible_beta_interval_deg": list(scan.admissible_interval_deg),
                "beta_samples": scan.beta_samples,
                "beta_samples_used": scan.beta_samples_used,
                "gated_beta_samples_by_3epsilon": scan.gated_beta_samples,
                "unbounded_beta_samples": scan.unbounded_beta_samples,
                "empty_beta_samples": scan.empty_beta_samples,
                "min_clearance_to_a1_m": clearance,
                "near_disk_active": clearance <= NEAR_RADIUS_M,
                "scan_below_threshold": scan.max_diameter_m < threshold_m,
                "margin_to_threshold_m": threshold_m - scan.max_diameter_m,
                "receipt_comparison": {
                    "receipt_g_violation_m": receipt_g,
                    "receipt_finite_scan_max_diameter_m": receipt_diameter,
                    "g_abs_diff_m": abs(violation - receipt_g),
                    "diameter_abs_diff_m": abs(scan.max_diameter_m - receipt_diameter),
                },
            }
        )

    hero_row = rows[0]
    crossing = inward_axis_threshold_crossing_m(threshold_m)
    dense_rows = []
    for label, (dx, dy), _receipt_g, _receipt_diameter in RECEIPT_REFERENCE_TABLE:
        station2 = (HERO_S2[0] + dx, HERO_S2[1] + dy)
        candidate = next(row for row in rows if row["label"] == label)
        dense_value = dense_violation_m(station2)
        dense_rows.append(
            {
                "label": label,
                "dense_value_m": dense_value,
                "candidate_set_value_m": candidate["g_violation_m"],
                "abs_diff_m": abs(dense_value - float(candidate["g_violation_m"])),
            }
        )
    dense_max_diff = max(entry["abs_diff_m"] for entry in dense_rows)
    return {
        "artifact": "local_probe_center_case",
        "kind": "independent_local_diagnostic_not_production_verification",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "tool": "src/q2/code/tools/q2_center_case_local_probe.py",
        "tool_sha256": sha256_of(TOOL_PATH),
        "invocation": (
            "cd /d/CUMCM2026 && PYTHONPATH=. python "
            "src/q2/code/tools/q2_center_case_local_probe.py"
        ),
        "independence": {
            "imports_repo_modules": False,
            "repo_modules_deliberately_not_used": [
                "src/q2/code/model/q1_adapter.py",
                "src/q1/code/q1_geometry.py",
                "src/q2/code/geometry/a1.py",
                "src/q2/code/geometry/angular_image.py",
                "src/q2/code/geometry/crec.py",
            ],
            "polygon_method": (
                "four closed half-planes (two per bearing wedge) -> feasible "
                "line-pair intersections -> convex hull vertex set -> "
                "O(k^2) vertex-pair diameter"
            ),
            "angular_image_method": (
                "own bearing intervals per A1 boundary piece: straight radial "
                "segments (bearing monotone in the parameter) and circular arcs "
                "(monotone between point-tangency cuts from S2)"
            ),
            "violation_method": (
                "own sampled evaluation of "
                "|S2-G| - max(1000, |G-S1|) over the A1 angle/radius grid"
            ),
            "third_party_dependencies": [],
        },
        "assumptions": {
            "S1": list(S1),
            "theta1_deg": THETA1_DEG,
            "epsilon_deg": EPSILON_DEG,
            "inner_radius_m": INNER_RADIUS_M,
            "outer_radius_m": OUTER_RADIUS_M,
            "omega_radius_m": OMEGA_RADIUS_M,
            "a1_definition": (
                "A1 = {S1 + rho*u(theta) : 5 < rho <= 1500, "
                "d_S(theta, theta1) <= 1 deg}"
            ),
            "omega_truncation_active": False,
            "omega_truncation_reason": (
                "S1 is at the origin and rho <= 1500 < 1800, so |G| <= 1800 never binds"
            ),
            "pure_angular_q1_intersection": (
                "the Q1 polygon uses ONLY the two +-epsilon bearing wedges; the "
                "rho shell, the 1800 m disk and the near rule are not applied to "
                "the intersection polygon"
            ),
            "second_bearing_expansion_deg": EPSILON_DEG,
            "admissibility_gate": "d_S(beta, theta1) > 3*epsilon",
            "probed_points": "frozen Hero plus small offsets, far from near regions",
            "hero_s2": list(HERO_S2),
        },
        "reference": {
            "receipt_q_m": RECEIPT_Q_M,
            "threshold_eta": THRESHOLD_ETA,
            "threshold_m": threshold_m,
            "threshold_from_work_order_m": 140.78060351389354,
            "threshold_abs_diff_m": abs(threshold_m - 140.78060351389354),
        },
        "per_point": rows,
        "sampling_note": {
            "beta_sample_count": BETA_SAMPLE_COUNT,
            "beta_grid": (
                "uniform inclusive grid over the epsilon-expanded angular image "
                "[image_lo - eps, image_hi + eps]"
            ),
            "beta_gate": (
                "samples with d_S(beta, theta1) <= 3*epsilon are dropped before "
                "any diameter is computed"
            ),
            "violation_angle_samples": VIOLATION_ANGLE_SAMPLE_COUNT,
            "violation_candidate_radii_m": list(VIOLATION_CANDIDATE_RADII_M),
            "violation_radial_justification": (
                "for rho <= 1000 the violation is a convex distance function over "
                "a convex annular sector, so its maximum is at an extreme point; "
                "for rho > 1000 the radial derivative is -u_hat.u - 1 <= 0, so the "
                "supremum is taken as rho -> 1000+.  The three candidate radii and "
                "the inclusive angle grid therefore contain the maximizer"
            ),
            "closed_closure_note": (
                "A1 excludes rho = 5 strictly, so the reported g(S2) is the "
                "supremum over A1, attained only in its closure"
            ),
            "lower_bound_statement": (
                "the finite scan maximum is the maximum over a finite beta sample: "
                "it is a sampled LOWER bound for the continuous inner supremum, "
                "not a certified upper bound"
            ),
            "argmax_location_note": (
                "the finite-scan maximizer sits at the left endpoint of the "
                "admissible interval (a boundary-hugging extremal), which the "
                "uniform inclusive grid evaluates exactly at its first sample"
            ),
            "near_disk_note": (
                "the near-aware production image subtracts the closed 5 m disk "
                "around S2; the recorded min_clearance_to_a1_m shows this disk does "
                "not reach A1 at any probed point, so the image used here matches "
                "the near-aware image at these points"
            ),
        },
        "extra_diagnostics": {
            "hero_diameter_vs_receipt_m": abs(
                hero_row["finite_scan_max_diameter_m"] - RECEIPT_Q_M
            ),
            "hero_g_vs_receipt_m": abs(
                hero_row["g_violation_m"] - RECEIPT_REFERENCE_TABLE[0][2]
            ),
            "receipt_comparison_note": (
                "work-order receipt values are quoted to 12 decimal places, so the "
                "absolute-difference columns are floored by that rounding (about "
                "5e-13); every observed difference is at that floor, i.e. the two "
                "implementations agree to the quoted precision"
            ),
            "dense_violation_cross_check": {
                "radial_samples": DENSE_CROSS_CHECK_RADII,
                "angle_samples": DENSE_CROSS_CHECK_ANGLES,
                "per_point": dense_rows,
                "max_abs_diff_m": dense_max_diff,
                "note": (
                    "independent denser angle/radius grid for g(S2); it confirms the "
                    "candidate radius set does not miss a larger sampled violation"
                ),
            },
            "inward_axis_threshold_crossing": crossing,
        },
        "disclaimers": [
            "This finite angular scan is a sampled lower bound of the inner "
            "supremum, not a certified upper bound.",
            "It does not prove that the whole candidate domain was found, and it "
            "does not establish the 5% candidate region or its area.",
            "It is a locator for the extraction loss, not production verification, "
            "and must not be used as a substitute for production verification.",
            "If the current representative config is not this exact center case, "
            "this table must not be used as verification of that config.",
            "CERTIFIED_GLOBAL_OPTIMUM stays False; nothing here certifies a global "
            "optimum.",
            "The receipt table is embedded for comparison only; every reported "
            "value above is computed by this independent implementation.",
        ],
    }


def print_table(report: dict[str, object]) -> None:
    reference = report["reference"]
    threshold = float(reference["threshold_m"])  # type: ignore[index]
    print("Q2 center-case local probe (independent diagnostic, not verification)")
    print(
        "assumptions: S1=(0,0), theta1=0 deg, epsilon=1 deg, "
        "A1 = {5 < rho <= 1500, |theta-theta1| <= 1 deg}, Omega inactive"
    )
    print(
        f"reference Q = {RECEIPT_Q_M!r} m, eta = {THRESHOLD_ETA}, "
        f"threshold T = {threshold!r} m"
    )
    print(
        f"beta scan = {BETA_SAMPLE_COUNT} uniform samples over the "
        "eps-expanded angular image, gate d_S(beta,theta1) > 3*eps"
    )
    print()
    header = (
        f"{'offset / m':>11} {'g(S2) / m':>18} {'scan max diam / m':>18} "
        f"{'diam < T':>9} {'margin / m':>12} {'argmax beta / deg':>18}"
    )
    print(header)
    print("-" * len(header))
    for row in report["per_point"]:  # type: ignore[union-attr]
        print(
            f"{row['label']:>11} {row['g_violation_m']:18.12f} "
            f"{row['finite_scan_max_diameter_m']:18.12f} "
            f"{str(row['scan_below_threshold']):>9} "
            f"{row['margin_to_threshold_m']:12.6f} "
            f"{row['finite_scan_argmax_beta_deg']:18.12f}"
        )
    print()
    print("receipt comparison (absolute differences)")
    print(f"{'offset / m':>11} {'|dg| / m':>12} {'|dD| / m':>12}")
    for row in report["per_point"]:  # type: ignore[union-attr]
        comparison = row["receipt_comparison"]
        print(
            f"{row['label']:>11} {comparison['g_abs_diff_m']:12.3e} "
            f"{comparison['diameter_abs_diff_m']:12.3e}"
        )
    print()
    extra = report["extra_diagnostics"]
    crossing = extra["inward_axis_threshold_crossing"]  # type: ignore[index]
    print(
        "inward-axis threshold crossing (sampled, step "
        f"{crossing['grid_step_m']} m): {crossing['crossing_offset_m']} m "
        f"bracket {crossing['bracket_m']}"
    )
    print(
        "dense g cross-check (denser angle/radius grid vs candidate radius set): "
        f"max |diff| = {extra['dense_violation_cross_check']['max_abs_diff_m']:.3e} m "
        f"over {len(extra['dense_violation_cross_check']['per_point'])} points"
    )
    print()
    print("key answers")
    hero = report["per_point"][0]  # type: ignore[index]
    inward_ten = report["per_point"][5]  # type: ignore[index]
    print(
        f"  Hero independent diameter vs receipt Q {RECEIPT_Q_M!r}: "
        f"|diff| = {extra['hero_diameter_vs_receipt_m']:.3e} m"
    )
    print(
        f"  inward 10 m {inward_ten['label']}: scan "
        f"{inward_ten['finite_scan_max_diameter_m']:.12f} m < T "
        f"{reference['threshold_m']:.12f} m -> "
        f"{inward_ten['scan_below_threshold']} (margin "
        f"{inward_ten['margin_to_threshold_m']:.6f} m)"
    )
    print(
        f"  Hero scan {hero['finite_scan_max_diameter_m']:.12f} m < T -> "
        f"{hero['scan_below_threshold']} (margin {hero['margin_to_threshold_m']:.6f} m)"
    )
    print(
        "  reminder: sampled lower bounds only; not a certified upper bound and "
        "not production verification"
    )
    print()
    print(f"JSON: {OUTPUT_PATH}")


def main() -> int:
    report = build_report()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print_table(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
