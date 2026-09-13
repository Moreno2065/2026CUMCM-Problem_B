"""Bounded source-service excursions during the compact Q3 certificate route.

The ordinary coverage action remains the reference.  An alternative is a
finite branch: service one observed source for at most a few actions, then
return to the *same* next certificate anchor.  Its return anchor and extra
path budget are controller state, so a favorable root estimate cannot turn
into repeated coverage starvation at runtime.

Hypothetical source maps are drawn only from the current observation state.
They rank executable actions; they never provide absence evidence or expose a
simulator source location.
"""
from __future__ import annotations

import copy
import math
import statistics
import time

from shapely.geometry import Point

from constraint_search.macro import worlds_from_observations
from geometry import constants as C
from policy import localization
from policy.scheduler import Mission
from state.channel_state import ChannelStatus

from .stop_fusion import EXCLUDE, replay


def _restore(policy, before):
    """Undo the reference coverage proposal before taking an excursion."""
    preserved = {name: policy.__dict__[name] for name in EXCLUDE
                 if name in policy.__dict__}
    policy.__dict__.clear()
    policy.__dict__.update(copy.deepcopy(before))
    policy.__dict__.update(preserved)


def _extra_path(start, via, anchor):
    return (math.dist(start, via) + math.dist(via, anchor)
            - math.dist(start, anchor))


def _measure_mission(channel, target, rank, anchor_index):
    return Mission(
        'measure', target, channel=channel.channel_id,
        meta={'kind': 'compact_coverage_branch_measure',
              'scan_variant': 'primary',
              'coverage_branch_rank': rank,
              'coverage_branch_anchor': anchor_index})


def _service_scan_mission(unknown_channels, channel, target, rank, anchor_index):
    """One service stop: discover a selected UNKNOWN set and one ACTIVE."""
    return Mission(
        'scan', target, channels=list(unknown_channels),
        meta={'kind': 'compact_coverage_branch_service_scan',
              'joint_channels': [channel.channel_id],
              'coverage_service_unknown_channels': list(unknown_channels),
              'coverage_branch_rank': rank,
              'coverage_branch_anchor': anchor_index,
              'truncate_at_cardinality': True})


def _measure_targets(policy, channel, position):
    """Geometry candidates whose value is decided only by full rollout cost."""
    points = list(policy._active_route_candidates(channel, position))
    seen = [tuple(obs['position']) for obs in channel.observations]
    try:
        points.extend(localization.candidate_points(
            channel, position,
            failed_points=policy.failed_points.get(channel.channel_id),
            opportunistic_reuse=True))
    except Exception:
        pass
    unique = []
    for point in points:
        point = tuple(point)
        if (any(math.dist(point, old) < 2.0 for old in seen)
                or any(math.dist(point, old) < 1.0 for old in unique)):
            continue
        unique.append(point)
    # This sorting only bounds branch count.  It does not score information:
    # the sampled complete-cost evaluation below chooses the action.
    unique.sort(key=lambda point: (math.dist(position, point), point))
    return unique[:policy.compact_coverage_rollout_points]


def _service_scan_sets(policy, ks, target):
    """All and small UNKNOWN scan sets for an already-paid service stop.

    A small set is ranked only by distance from each channel's current
    feasible region to the stop. It does not create evidence for omitted
    channels, and a full-completion rollout decides whether either the subset
    or all-channel scan is actually worth its measurement time.
    """
    all_channels = tuple(ch.channel_id for ch in ks.unknown)
    if not all_channels:
        return []
    sets = [all_channels]
    limit = policy.compact_coverage_rollout_service_channels
    if limit <= 0 or limit >= len(all_channels):
        return sets
    point = Point(target)

    def key(ch):
        try:
            region = getattr(ch, 'position_set', None)
            distance = region.distance(point) if region is not None else math.inf
        except Exception:
            distance = math.inf
        return (float(distance), ch.channel_id)

    ranked = sorted(ks.unknown, key=key)
    for size in (limit, min(len(ranked) - 1, 2 * limit)):
        if size <= 0:
            continue
        subset = tuple(ch.channel_id for ch in ranked[:size])
        if subset not in sets:
            sets.append(subset)
    return sets


def _anchor_scan_mission(policy, ks, anchor_index, active_override=None):
    """Preview one real certificate scan without consuming its anchor yet.

    ``active_override`` is deliberately a list of *already eligible* ACTIVE
    channels, rather than a new value heuristic.  It lets a posterior rollout
    ask whether a bearing that costs six seconds at this station really saves
    a later trip.  UNKNOWN channels remain unchanged, so a pruning candidate
    can never weaken the absence certificate.
    """
    target = tuple(policy._coverage_points[anchor_index])
    def direction_count(channel):
        return sum(obs.get("result") == "direction"
                   for obs in channel.observations)

    active = [ch.channel_id for ch in ks.by_status(ChannelStatus.ACTIVE)
              if ch.mec_radius > policy.compact_active_stop_radius
              and not policy.fallback.in_fallback(ch.channel_id)
              and (policy.compact_ring_active_max_directions <= 0 or
                   direction_count(channel) <
                   policy.compact_ring_active_max_directions)]
    if policy.compact_terminal_scan_radius > 0.0:
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            cid = ch.channel_id
            if (cid in active or policy.fallback.in_fallback(cid)
                    or ch.mec is None
                    or ch.mec_radius > policy.compact_terminal_scan_radius
                    or (policy.compact_ring_active_max_directions > 0 and
                        direction_count(ch) >=
                        policy.compact_ring_active_max_directions)
                    or any(math.dist(obs["position"], target) < 2.0
                           for obs in ch.observations)):
                continue
            center, radius = ch.mec
            if math.dist(target, center) + radius > C.R_EFF_MIN + 1e-9:
                continue
            try:
                step = localization._adaptive_step(ch.feasible_region, target)
                worst = localization._eval_worst(
                    ch.feasible_region, target, step, mode="radius")
            except Exception:
                continue
            if worst <= policy.compact_terminal_scan_worst + 1e-9:
                active.append(cid)
    if active_override is not None:
        eligible = set(active)
        active = [cid for cid in active_override if cid in eligible]
    return Mission(
        "scan", target, channels=[ch.channel_id for ch in ks.unknown],
        meta={"kind": "compact_ring", "coverage_scan": True,
              "coverage_anchor_index": anchor_index,
              "joint_channels": active,
              "truncate_at_cardinality":
              policy.compact_truncate_active_at_cardinality})


def anchor_candidates(policy, ks, position, base):
    """When joint routing selects service, compare immediate certificate work.

    This is the reverse of :func:`candidates`: rather than inserting a source
    before an anchor, it asks whether forcing a nearby still-pending anchor is
    cheaper over a complete posterior replay than following the selected
    source action.  The returned plan only consumes the anchor once selected.
    """
    if (base is None or not policy.compact_joint_ring_route or
            base.meta.get("kind") not in (
                "compact_joint_ring_clear", "compact_joint_ring_measure") or
            not policy._coverage_remaining):
        return []
    items = [(-(index + 1), policy._coverage_points[index], "anchor")
             for index in policy._coverage_remaining]
    ordered = policy._hybrid_open_order(items, position,
                                        or_opt=policy.compact_joint_ring_or_opt)
    result = []
    for cid, _, _ in ordered[:2]:
        index = -cid - 1
        result.append((_anchor_scan_mission(policy, ks, index),
                       {"root_kind": "anchor", "anchor_index": index}))
    return result


def anchor_scan_pruning_candidates(policy, ks, base):
    """Same-stop ACTIVE scan alternatives for a certificate action.

    The normal compact ring measures every large ACTIVE channel whenever it
    visits an anchor.  That is often useful, but it is still an irreversible
    six-second spend per channel.  For a real anchor action, compare omitting
    one such bearing (and, when small enough, all of them) by replaying the
    *whole remaining policy*.  The returned alternatives consume the same
    anchor and scan precisely the same UNKNOWN set as ``base``; only optional
    ACTIVE measurements differ.

    We do not use a radius or information-gain threshold to choose an
    omission.  The bounded posterior rollout decides whether the omitted
    channel causes a later detour that outweighs its measurement cost.
    """
    if (base is None or base.meta.get("kind") != "compact_ring" or
            not base.meta.get("coverage_scan") or
            not policy._coverage_remaining):
        return []
    index = base.meta.get("coverage_anchor_index")
    if not isinstance(index, int) or index not in policy._coverage_remaining:
        return []
    active = list(base.meta.get("joint_channels", ()))
    if not active:
        return []
    # The normal anchor proposal can contain terminal measurements which are
    # not in the large-ACTIVE set reconstructed by _anchor_scan_mission.
    # Preserve exactly its action set, then remove one item at a time.
    result = []
    for cid in sorted(active)[:policy.compact_coverage_rollout_candidates]:
        kept = [other for other in active if other != cid]
        mission = Mission(
            "scan", tuple(base.target),
            channels=[ch.channel_id for ch in ks.unknown],
            meta={"kind": "compact_ring", "coverage_scan": True,
                  "coverage_anchor_index": index,
                  "joint_channels": kept,
                  "truncate_at_cardinality":
                  policy.compact_truncate_active_at_cardinality,
                  "rollout_pruned_active_channel": cid})
        result.append((mission, {"root_kind": "anchor",
                                 "anchor_index": index,
                                 "pruned_channel": cid}))
    # "Scan no ACTIVE here" is a distinct route-level choice.  Keep it only
    # for small sets so a coverage decision remains computationally bounded.
    if 1 < len(active) <= 3:
        mission = Mission(
            "scan", tuple(base.target),
            channels=[ch.channel_id for ch in ks.unknown],
            meta={"kind": "compact_ring", "coverage_scan": True,
                  "coverage_anchor_index": index,
                  "joint_channels": [],
                  "truncate_at_cardinality":
                  policy.compact_truncate_active_at_cardinality,
                  "rollout_pruned_active_channel": "all"})
        result.append((mission, {"root_kind": "anchor",
                                 "anchor_index": index,
                                 "pruned_channel": "all"}))
    return result


def density_candidates(policy, before, after, ks, position):
    """Offer one denser certificate suffix as a real first action.

    The candidate is constructed from the state immediately after the first
    *executed* anchor scan (``before``).  It commits a legal replacement
    certificate and visits one of its unvisited points.  Therefore it can be
    compared against either a source-service action or the ordinary next
    anchor with exactly the same posterior full-cost replay machinery.

    This is intentionally not a count threshold: source number remains
    hidden, and the rollout is allowed to reject a dense ring even when only
    a few channels happened to be discovered at the first station.
    """
    if not policy.compact_adaptive_ring_rollout:
        return []
    _restore(policy, before)
    try:
        candidate = policy._adaptive_ring_candidate(ks)
        if candidate is None:
            return []
        points, known = candidate
        policy._coverage_points = [tuple(point) for point in points]
        policy.compact_ring_points = len(points)
        policy.compact_ring_outer_points = len(points)
        policy._coverage_remaining = set(range(1, len(points)))
        policy._coverage_index = 1
        items = [(-(index + 1), policy._coverage_points[index], "anchor")
                 for index in policy._coverage_remaining]
        ordered = policy._hybrid_open_order(
            items, position, or_opt=policy.compact_joint_ring_or_opt)
        if not ordered:
            return []
        index = -ordered[0][0] - 1
        mission = _anchor_scan_mission(policy, ks, index)
        mission.meta["rollout_adaptive_density"] = True
        plan = {"root_kind": "density_anchor", "anchor_index": index,
                "points": [list(point) for point in points], "known": known}
        return [(mission, plan)]
    finally:
        _restore(policy, after)


def certificate_template_candidates(policy, before, after, ks, position):
    """Offer service-certificate templates only through full-cost replay.

    The static template score is a route proxy.  It is useful to construct a
    finite legal candidate, but it cannot predict how a new bearing result
    changes later localisation.  Here every proposed template begins with one
    of its real service stops; the posterior replay then executes its scans,
    validates its UNKNOWN witnesses, and follows the normal policy to
    completion.  No anchor is removed until that execution reaches the
    existing callback in the real runner.
    """
    if (not policy.compact_service_certificate or
            not policy.compact_service_certificate_rollout):
        return []
    _restore(policy, before)
    try:
        if policy._certificate_service_template is not None:
            return []
        proposal = policy._certificate_service_template_candidate(ks, position)
        if proposal is None:
            return []
        saving, removed, services = proposal
        template = {
            "remove_anchors": list(removed),
            "services": copy.deepcopy(services),
            "remaining_services": [node["key"] for node in services],
            "projected_saving_m": float(saving),
        }
        result = []
        for node in services:
            if node["kind"] == "clear":
                unknown = [ch.channel_id for ch in ks.unknown
                           if not any(math.dist(obs["position"], node["point"]) < 2.0
                                      for obs in ch.observations)]
                mission = Mission(
                    "clear", node["point"], channel=node["channel"],
                    meta={"kind": "compact_service_certificate_clear",
                          "certificate_service_key": node["key"],
                          "certificate_service_channel": node["channel"],
                          "certificate_unknown_channels":
                          [ch.channel_id for ch in ks.unknown],
                          "post_clear_channels": unknown,
                          "truncate_at_cardinality":
                          policy.compact_truncate_active_at_cardinality})
            else:
                joint = [node["channel"]] if (
                    node["channel"] in ks.channels and
                    ks[node["channel"]].status == ChannelStatus.ACTIVE) else []
                mission = Mission(
                    "scan", node["point"],
                    channels=[ch.channel_id for ch in ks.unknown],
                    meta={"kind": "compact_service_certificate",
                          "coverage_scan": True,
                          "joint_channels": joint,
                          "certificate_service_key": node["key"],
                          "certificate_service_channel": node["channel"],
                          "truncate_at_cardinality":
                          policy.compact_truncate_active_at_cardinality})
            result.append((mission, {"root_kind": "service_certificate_template",
                                     "template": template,
                                     "root_service_key": node["key"]}))
        return result
    finally:
        _restore(policy, after)


def candidates(policy, ks, position, base):
    """Return finite service branches which reconnect to ``base``'s anchor."""
    if (base is None or base.meta.get('kind') != 'compact_ring'
            or base.target is None):
        return []
    # A joint certificate route can issue anchor 6 when ``_coverage_index``
    # only means "two anchors were consumed".  The issued mission is the
    # authoritative reconnect identity.  Keep the ordinal fallback for old
    # replay traces that predate this metadata.
    anchor_index = base.meta.get('coverage_anchor_index',
                                 policy._coverage_index)
    if (not isinstance(anchor_index, int) or anchor_index < 0 or
            anchor_index >= len(policy._coverage_points)):
        return []
    anchor = tuple(base.target)
    return_orders = [('same_anchor', (anchor_index,))]
    if policy.compact_joint_ring_route:
        # There is no meaningful ``index + 1`` in a globally re-ordered ring.
        # Restrict the local rebuild to two nearby unvisited certificate
        # points.  Each candidate still gets a complete rollout comparison.
        next_indices = sorted(
            policy._coverage_remaining,
            key=lambda index: (math.dist(anchor,
                                         policy._coverage_points[index]),
                               index))[:2]
    else:
        next_index = anchor_index + 1
        next_indices = ([next_index]
                        if next_index in policy._coverage_remaining else [])
    for next_index in next_indices:
        # Rebuild A -> B as source -> B -> A. Both anchors remain in the
        # certificate and are only credited after their real scans execute.
        return_orders.append(('swap_two_anchors',
                              (next_index, anchor_index)))
    ranked = []
    for channel in ks.ready:
        if channel.channel_id in policy.blocked:
            continue
        target = policy._clear_target(channel, position)
        for variant, order in return_orders:
            reconnect = policy._coverage_points[order[0]]
            extra = _extra_path(position, target, reconnect)
            if extra <= policy.compact_coverage_branch_detour_m + 1e-9:
                ranked.append((extra, channel.channel_id, 'clear', target, 0,
                               variant, order))
    for channel in ks.active:
        cid = channel.channel_id
        if (cid in policy.blocked or policy.fallback.in_fallback(cid)
                or policy._compact_route_attempts.get(cid, 0)
                >= policy.compact_route_active_attempts):
            continue
        for rank, target in enumerate(_measure_targets(policy, channel, position)):
            for variant, order in return_orders:
                reconnect = policy._coverage_points[order[0]]
                extra = _extra_path(position, target, reconnect)
                if extra <= policy.compact_coverage_branch_detour_m + 1e-9:
                    ranked.append((extra, cid, 'measure', target, rank,
                                   variant, order))
                    if policy.compact_coverage_rollout_service_scan:
                        for channels in _service_scan_sets(policy, ks, target):
                            ranked.append((extra, cid, 'service_scan', target,
                                           rank, variant, order, channels))
    # A smaller service scan is evaluated before its all-channel sibling when
    # its route terms are identical. The full scan remains a legal candidate.
    ranked.sort(key=lambda row: (row[0], row[1], row[4], row[5],
                                 len(row[7]) if len(row) > 7 else 0,
                                 row[2], row[3]))
    result = []
    for row in ranked:
        extra, cid, kind, target, rank, variant, order = row[:7]
        scan_channels = row[7] if len(row) > 7 else None
        if len(result) >= policy.compact_coverage_rollout_candidates:
            break
        channel = ks[cid]
        if kind == 'clear':
            post = policy._post_clear_channels(ks, target, exclude=cid)
            meta = {'kind': 'compact_coverage_branch_clear',
                    'risky_probe': True, 'compact_ring': True,
                    'coverage_branch_anchor': order[0],
                    'coverage_branch_rank': rank,
                    'post_clear_channels': []}
            if post is not None:
                meta['post_clear_channels'] = post
            mission = Mission('clear', target, channel=cid, meta=meta)
        elif kind == 'measure':
            mission = _measure_mission(channel, target, rank, order[0])
        else:
            mission = _service_scan_mission(scan_channels, channel, target,
                                            rank, order[0])
        plan = {'cid': cid, 'anchor_index': order[0],
                'anchor': policy._coverage_points[order[0]],
                'return_indices': list(order), 'return_issued': None,
                'remaining': policy.compact_coverage_branch_actions - 1,
                'extra_spent_m': extra,
                'extra_limit_m': policy.compact_coverage_branch_detour_m,
                'root_kind': kind, 'variant': variant}
        result.append((mission, plan))
    return result


def post_service_candidates(policy, ks, position, base):
    """Zero-movement UNKNOWN scans after a real source-service stop.

    The ordinary branch comparison catches a source clear only when the next
    decision happens to be a certificate anchor.  A joint source route often
    chooses another source next.  In that case, leaving immediately can throw
    away an already-paid discovery stop.  These candidates scan only UNKNOWN
    channels and then replan from real outcomes; they do not assert absence,
    consume an anchor, or carry a synthetic branch state.
    """
    if (not policy.compact_coverage_rollout_post_service_scan or
            not policy._coverage_remaining or
            base is None or base.meta.get('kind') == 'compact_ring'):
        return []
    paid = getattr(policy, '_compact_service_current', None)
    if paid is None or math.dist(position, paid) >= 2.0:
        return []
    result = []
    for channels in _service_scan_sets(policy, ks, position):
        result.append((Mission(
            'scan', tuple(position), channels=list(channels),
            meta={'kind': 'compact_post_service_scan',
                  'coverage_service_unknown_channels': list(channels),
                  'truncate_at_cardinality': True}), None))
    return result


def _arm(policy, plan, mission):
    """Mirror root-action bookkeeping in real and hypothetical execution."""
    if plan.get("root_kind") == "density_anchor":
        points = [tuple(point) for point in plan["points"]]
        policy._commit_adaptive_ring(points, plan["known"], rollout=True)
        index = int(plan["anchor_index"])
        if index not in policy._coverage_remaining:
            return
        policy._coverage_remaining.discard(index)
        policy._coverage_index = policy.compact_ring_points - len(
            policy._coverage_remaining)
        policy.compact_stats["ring_stops"] += 1
        policy.compact_stats["joint_active_planned"] += len(
            mission.meta.get("joint_channels", ()))
        return
    if plan.get("root_kind") == "service_certificate_template":
        raw = plan["template"]
        policy._certificate_service_template = {
            "remove_anchors": set(raw["remove_anchors"]),
            "services": copy.deepcopy(raw["services"]),
            "remaining_services": set(raw["remaining_services"]),
        }
        policy.compact_stats["service_certificate_candidates"] += 1
        policy.compact_stats["service_certificate_templates"] += 1
        policy.compact_stats["service_certificate_route_saving_m"] += (
            float(raw.get("projected_saving_m", 0.0)))
        return
    if plan.get("root_kind") == "anchor":
        index = int(plan["anchor_index"])
        if index not in policy._coverage_remaining:
            return
        policy._coverage_remaining.discard(index)
        if policy.compact_joint_ring_route or policy.compact_service_certificate:
            policy._coverage_index = (policy.compact_ring_points -
                                      len(policy._coverage_remaining))
        else:
            while (policy._coverage_index not in policy._coverage_remaining
                   and policy._coverage_index < policy.compact_ring_points):
                policy._coverage_index += 1
        policy.compact_stats["ring_stops"] += 1
        policy.compact_stats["joint_active_planned"] += len(
            mission.meta.get("joint_channels", ()))
        return
    policy._compact_coverage_branch = copy.deepcopy(plan)
    cid = plan['cid']
    if mission.kind in ('measure', 'scan'):
        policy._compact_route_attempts[cid] = (
            policy._compact_route_attempts.get(cid, 0) + 1)
    else:
        policy._compact_attempted.add(cid)
        policy._compact_inflight = (cid, tuple(mission.target))


def _setup(plan, mission):
    def apply(policy):
        _arm(policy, plan, mission)
    return apply


def _setup_post_service_scan(policy):
    """The one paid stop may be scanned once, never recursively."""
    policy._compact_service_current = None
    policy._compact_service_pending = None


def choose(policy, before, after, ks, position, current_channel, base):
    """Compare normal coverage against complete, budgeted service branches."""
    stats = policy.coverage_rollout_stats
    if (base is None or policy.compact_coverage_rollout_budget <= 0.0
            or policy.fallback.active_fallbacks()
            or stats['wall_s'] >= policy.compact_coverage_rollout_budget):
        return base
    branch_choices = candidates(policy, ks, position, base)
    anchor_choices = anchor_candidates(policy, ks, position, base)
    scan_choices = anchor_scan_pruning_candidates(policy, ks, base)
    density_choices = density_candidates(policy, before, after, ks, position)
    policy.compact_stats["adaptive_ring_rollout_candidates"] += len(
        density_choices)
    post_choices = post_service_candidates(policy, ks, position, base)
    template_choices = certificate_template_candidates(
        policy, before, after, ks, position)
    # Same-stop pruning is cheap to replay and directly tests whether a
    # measurement eliminates a later task.  Put it before detour branches so
    # a tight real-time rollout budget cannot starve this comparison.
    choices = (density_choices + template_choices + scan_choices + branch_choices +
               anchor_choices + post_choices)
    if not choices:
        return base
    started = time.perf_counter()
    deadline = started + max(0.0, policy.compact_coverage_rollout_budget
                             - stats['wall_s'])
    stats['searches'] += 1
    decision = stats['searches']
    worlds = worlds_from_observations(
        ks, policy.compact_coverage_rollout_worlds,
        ('compact-coverage', decision))
    owner = getattr(policy.stop_planner, '__self__', None)
    config = copy.deepcopy(owner.config) if owner is not None else None
    costs, selected = [], 0
    entries = [(base, after, None)] + [
        (mission, before,
         _setup(plan, mission) if plan is not None else _setup_post_service_scan)
        for mission, plan in choices]
    if worlds and config is not None:
        for mission, saved, setup in entries:
            values = []
            for world_id, world in enumerate(worlds):
                value = replay(saved, ks, position, current_channel, mission,
                               world, config,
                               ('compact-coverage', decision, world_id),
                               deadline,
                               limit=policy.compact_coverage_rollout_step_limit,
                               policy_setup=setup)
                values.append(value)
                stats['branches'] += 1
                if not math.isfinite(value) or time.perf_counter() >= deadline:
                    break
            if len(values) != len(worlds) or not all(math.isfinite(v)
                                                      for v in values):
                costs.append(None)
                stats['incomplete_candidates'] += 1
            else:
                costs.append(values)
            if time.perf_counter() >= deadline:
                break
        if costs and costs[0] is not None:
            best_gain = policy.compact_coverage_rollout_margin_s
            for index, values in enumerate(costs[1:], 1):
                if values is None:
                    continue
                gains = [reference - candidate
                         for reference, candidate in zip(costs[0], values)]
                score = statistics.median(gains)
                wins = sum(gain > 0.0 for gain in gains) / len(gains)
                if (score >= best_gain
                        and wins >= policy.compact_coverage_rollout_min_win_fraction
                        and min(gains) >= -policy.compact_coverage_rollout_margin_s):
                    best_gain, selected = score, index
    else:
        stats['world_failures'] += 1
    stats['overrides'] += int(selected != 0)
    stats['wall_s'] += time.perf_counter() - started
    policy.coverage_rollout_log.append({
        'decision': decision,
        'chosen': selected,
        'base': {'kind': base.kind, 'target': list(base.target),
                 'costs': costs[0] if costs else None},
        'branches': [
            {'kind': mission.kind, 'channel': mission.channel,
             'target': list(mission.target), 'plan': plan,
             'costs': costs[index + 1] if index + 1 < len(costs) else None}
            for index, (mission, plan) in enumerate(choices)],
    })
    if selected:
        _restore(policy, before)
        mission, plan = choices[selected - 1]
        if plan is None:
            _setup_post_service_scan(policy)
        else:
            _arm(policy, plan, mission)
    elif post_choices:
        # ``_compact_decide`` may already have issued another source mission.
        # It is not a future paid stop for this decision, so do not let it
        # keep offering a scan at the old location.
        policy._compact_service_current = None
    return entries[selected][0]
