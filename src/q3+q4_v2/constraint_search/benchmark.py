"""Paired full episodes, action ledger audit and independent truth containment."""
from __future__ import annotations
import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "baseline" / "code"), str(ROOT / "tools")]

from shapely.geometry import Point
import runtime
import production
from check_plan_execution import AuditingRunner
from learned_search.scheduler import LearnedSearchScheduler
from constraint_search.scheduler import ConstraintSearchScheduler
from constraint_search.macro import ConstraintMacroScheduler
from compact_ring.scheduler import CompactRingScheduler


class TruthAuditingRunner(AuditingRunner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.truth_checks = 0
        self.truth_failures = []

    def _execute(self, mission):
        super()._execute(mission)
        for source in self.simulator.sources:
            ch = self.ks[source.channel]
            region = getattr(ch, "position_set", None)
            if region is not None:
                self.truth_checks += 1
                if region.is_empty or region.distance(Point(source.pos)) > 1e-6:
                    self.truth_failures.append({"step": self._step,
                                                "channel": source.channel})


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--seeds', nargs='+', type=int, default=[101, 303, 505])
    p.add_argument('--counts', nargs='+', type=int, default=[10, 13, 15, 16])
    p.add_argument('--scenario', default='random')
    p.add_argument('--tag', default='screen')
    p.add_argument('--policies', nargs='+', choices=['production', 'constraints', 'macro', 'compact'],
                   default=['production', 'constraints'])
    p.add_argument('--segment-budget', type=float, default=60.)
    p.add_argument('--segment-margin', type=float, default=100.)
    p.add_argument('--segment-min-win-fraction', type=float, default=1.)
    p.add_argument('--compact-performance-preset', action='store_true')
    p.add_argument('--compact-joint-service-preset', action='store_true')
    p.add_argument('--compact-ring-radius', type=float, default=940.)
    p.add_argument('--compact-ring-points', type=int, default=8)
    p.add_argument('--compact-ring-active-max-directions', type=int, default=0)
    p.add_argument('--compact-center-anchor', action='store_true')
    p.add_argument('--compact-center-warmup-resultant-threshold', type=float,
                   default=0.)
    p.add_argument('--compact-center-warmup-min-stops', type=int, default=3)
    p.add_argument('--compact-coverage-optical-max-points', type=int, default=0)
    p.add_argument('--compact-coverage-optical-max-entries', type=int, default=1)
    p.add_argument('--compact-coverage-optical-max-entry', type=float, default=0.)
    p.add_argument('--compact-active-stop-radius', type=float, default=80.)
    p.add_argument('--compact-enroute-clear-radius', type=float, default=20.)
    p.add_argument('--compact-enroute-detour', type=float, default=350.)
    p.add_argument('--compact-probe-radius', type=float, default=0.)
    p.add_argument('--compact-optical-cover-points', type=int, default=10)
    p.add_argument('--compact-finish-active-at-cap', action='store_true')
    p.add_argument('--compact-route-active',
                   action=argparse.BooleanOptionalAction, default=True)
    p.add_argument('--compact-route-active-attempts', type=int, default=3)
    p.add_argument('--compact-enroute-measure-detour', type=float, default=350.)
    p.add_argument('--compact-route-cluster-radius', type=float, default=0.)
    p.add_argument('--compact-route-cluster-max', type=int, default=0)
    p.add_argument('--compact-route-cluster-min-saving', type=float, default=35.)
    p.add_argument('--compact-route-alternatives', action='store_true')
    p.add_argument('--compact-fusion-budget', type=float, default=0.)
    p.add_argument('--compact-fusion-worlds', type=int, default=4)
    p.add_argument('--compact-fusion-margin', type=float, default=10.)
    p.add_argument('--compact-fusion-views-only', action='store_true')
    p.add_argument('--compact-clear-region-route', action='store_true')
    p.add_argument('--compact-route-quality-slack', type=float, default=5.)
    p.add_argument('--compact-route-point-passes', type=int, default=2)
    p.add_argument('--compact-shape-cover', action='store_true')
    p.add_argument('--compact-route-free-probe-radius', type=float, default=0.)
    p.add_argument('--compact-local-finish-steps', type=int, default=0)
    p.add_argument('--compact-local-finish-budget', type=float, default=0.)
    p.add_argument('--compact-local-finish-max-radius', type=float, default=80.)
    p.add_argument('--compact-local-finish-min-shrink', type=float, default=.05)
    p.add_argument('--compact-local-finish-min-known', type=int, default=0)
    p.add_argument('--compact-terminal-scan-radius', type=float, default=0.)
    p.add_argument('--compact-terminal-scan-worst', type=float, default=20.)
    p.add_argument('--compact-post-clear-worst', type=float, default=0.)
    p.add_argument('--compact-joint-ring-route', action='store_true')
    p.add_argument('--compact-joint-ring-max-known', type=int, default=0)
    p.add_argument('--compact-joint-ring-min-stops', type=int, default=0)
    p.add_argument('--compact-joint-ring-active-radius', type=float,
                   default=None)
    p.add_argument('--compact-joint-ring-active-attempts', type=int,
                   default=None)
    p.add_argument('--compact-joint-ring-min-directions', type=int,
                   default=1)
    p.add_argument('--compact-joint-ring-service-worst', type=float,
                   default=0.)
    p.add_argument('--compact-joint-ring-or-opt', action='store_true')
    p.add_argument('--compact-joint-clear-witness', action='store_true')
    p.add_argument('--compact-joint-clear-witness-useful-only',
                   action='store_true')
    p.add_argument('--compact-joint-clear-witness-max-unknown', type=int,
                   default=0)
    p.add_argument('--compact-joint-anchor-substitution', action='store_true')
    p.add_argument('--compact-joint-anchor-substitution-max-unknown', type=int,
                   default=0)
    p.add_argument('--compact-service-certificate', action='store_true')
    p.add_argument('--compact-service-certificate-radius', type=float, default=250.)
    p.add_argument('--compact-service-certificate-max-services', type=int,
                   default=8)
    p.add_argument('--compact-service-certificate-depth', type=int, default=2)
    p.add_argument('--compact-service-certificate-active-candidates', type=int,
                   default=1)
    p.add_argument('--compact-service-certificate-rollout', action='store_true')
    p.add_argument('--compact-service-certificate-min-saving', type=float,
                   default=35.)
    p.add_argument('--compact-tail-rollout-budget', type=float, default=0.)
    p.add_argument('--compact-tail-rollout-worlds', type=int, default=4)
    p.add_argument('--compact-tail-rollout-candidates', type=int, default=10)
    p.add_argument('--compact-tail-rollout-margin', type=float, default=15.)
    p.add_argument('--compact-tail-rollout-min-win-fraction', type=float,
                   default=.75)
    p.add_argument('--compact-tail-rollout-objective',
                   choices=('mean', 'median'), default='median')
    p.add_argument('--compact-tail-rollout-step-limit', type=int, default=180)
    p.add_argument('--compact-coverage-rollout-budget', type=float, default=0.)
    p.add_argument('--compact-coverage-rollout-worlds', type=int, default=3)
    p.add_argument('--compact-coverage-rollout-candidates', type=int, default=5)
    p.add_argument('--compact-coverage-rollout-points', type=int, default=3)
    p.add_argument('--compact-coverage-rollout-service-scan', action='store_true')
    p.add_argument('--compact-coverage-rollout-service-channels', type=int,
                   default=0)
    p.add_argument('--compact-coverage-rollout-post-service-scan',
                   action='store_true')
    p.add_argument('--compact-coverage-rollout-margin', type=float, default=10.)
    p.add_argument('--compact-coverage-rollout-min-win-fraction', type=float,
                   default=.75)
    p.add_argument('--compact-coverage-branch-actions', type=int, default=2)
    p.add_argument('--compact-coverage-branch-detour', type=float, default=350.)
    p.add_argument('--compact-coverage-rollout-step-limit', type=int, default=220)
    p.add_argument('--compact-adaptive-ring-points', type=int, default=0)
    p.add_argument('--compact-adaptive-ring-radius', type=float, default=0.)
    p.add_argument('--compact-adaptive-ring-known-max', type=int, default=-1)
    p.add_argument('--compact-adaptive-ring-rollout', action='store_true')
    p.add_argument('--resume', action='store_true',
                   help='append only missing (N, seed, policy) rows to this tag')
    args = p.parse_args()
    if args.compact_joint_service_preset:
        args.compact_performance_preset = True
        args.compact_joint_ring_route = True
        args.compact_joint_ring_active_radius = 200.
        args.compact_joint_ring_service_worst = 20.
        args.compact_joint_anchor_substitution = True
    if args.compact_performance_preset:
        args.compact_terminal_scan_radius = 80.0
        args.compact_terminal_scan_worst = 20.0
        args.compact_local_finish_steps = 2
        args.compact_local_finish_budget = 300.0
        args.compact_local_finish_max_radius = 80.0
        args.compact_local_finish_min_shrink = 0.05
        args.compact_local_finish_min_known = 14
    out = ROOT / 'tuning_runs' / 'constraint_search' / args.tag
    out.mkdir(parents=True, exist_ok=True)
    result_path = out / 'results.json'
    if result_path.exists() and not args.resume:
        raise SystemExit('Choose a new --tag; existing results are immutable')
    hashes = {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
              for f in [ROOT / 'runtime.py', ROOT / 'production.py',
                        ROOT / 'constraint_search' / 'state.py',
                        ROOT / 'constraint_search' / 'scheduler.py',
                        ROOT / 'constraint_search' / 'macro.py',
                        ROOT / 'compact_ring' / 'scheduler.py',
                        ROOT / 'compact_ring' / 'stop_fusion.py',
                        ROOT / 'compact_ring' / 'tail_rollout.py',
                        ROOT / 'compact_ring' / 'coverage_rollout.py',
                        ROOT / 'compact_ring' / 'region_route.py',
                        ROOT / 'belief_rollout' / 'worlds.py',
                        ROOT / 'learned_search' / 'scheduler.py']}
    runtime.V2GameRunner = TruthAuditingRunner
    rows = (json.loads(result_path.read_text(encoding='utf-8'))['rows']
            if result_path.exists() else [])
    completed = {(r['n'], r['seed'], r['policy']) for r in rows}
    for n in args.counts:
        for seed in args.seeds:
            for name in args.policies:
                if (n, seed, name) in completed:
                    continue
                cls = {'production': LearnedSearchScheduler,
                       'constraints': ConstraintSearchScheduler,
                       'macro': ConstraintMacroScheduler,
                       'compact': CompactRingScheduler}[name]
                target = out / f'Q3_{n}_{seed}' / name
                cfg = production.scheduler_kwargs('Q3')
                if name in ('macro', 'compact'):
                    cfg.update(segment_budget=args.segment_budget,
                               segment_margin=args.segment_margin,
                               segment_min_win_fraction=args.segment_min_win_fraction)
                if name == 'compact':
                    cfg.update(
                        compact_ring_radius=args.compact_ring_radius,
                        compact_ring_points=args.compact_ring_points,
                        compact_ring_active_max_directions=
                        args.compact_ring_active_max_directions,
                        compact_center_anchor=args.compact_center_anchor,
                        compact_center_warmup_resultant_threshold=
                        args.compact_center_warmup_resultant_threshold,
                        compact_center_warmup_min_stops=
                        args.compact_center_warmup_min_stops,
                        compact_coverage_optical_max_points=
                        args.compact_coverage_optical_max_points,
                        compact_coverage_optical_max_entries=
                        args.compact_coverage_optical_max_entries,
                        compact_coverage_optical_max_entry_m=
                        args.compact_coverage_optical_max_entry,
                        compact_active_stop_radius=args.compact_active_stop_radius,
                        compact_enroute_clear_radius=args.compact_enroute_clear_radius,
                        compact_enroute_detour=args.compact_enroute_detour,
                        compact_probe_radius=args.compact_probe_radius,
                        compact_optical_cover_points=
                        args.compact_optical_cover_points,
                        compact_truncate_active_at_cardinality=
                        not args.compact_finish_active_at_cap,
                        compact_route_active=args.compact_route_active,
                        compact_route_active_attempts=
                        args.compact_route_active_attempts,
                        compact_enroute_measure_detour=
                        args.compact_enroute_measure_detour,
                        compact_route_cluster_radius=
                        args.compact_route_cluster_radius,
                        compact_route_cluster_max=args.compact_route_cluster_max,
                        compact_route_cluster_min_saving=
                        args.compact_route_cluster_min_saving,
                        compact_route_alternatives=args.compact_route_alternatives,
                        compact_fusion_budget=args.compact_fusion_budget,
                        compact_fusion_worlds=args.compact_fusion_worlds,
                        compact_fusion_margin=args.compact_fusion_margin,
                        compact_fusion_views_only=args.compact_fusion_views_only,
                        compact_clear_region_route=args.compact_clear_region_route,
                        compact_route_quality_slack=args.compact_route_quality_slack,
                        compact_route_point_passes=
                        args.compact_route_point_passes,
                        compact_shape_cover=args.compact_shape_cover,
                        compact_route_free_probe_radius=
                        args.compact_route_free_probe_radius,
                        compact_local_finish_steps=args.compact_local_finish_steps,
                        compact_local_finish_budget=args.compact_local_finish_budget,
                        compact_local_finish_max_radius=
                        args.compact_local_finish_max_radius,
                        compact_local_finish_min_shrink=
                        args.compact_local_finish_min_shrink,
                        compact_local_finish_min_known=
                        args.compact_local_finish_min_known,
                        compact_terminal_scan_radius=
                        args.compact_terminal_scan_radius,
                        compact_terminal_scan_worst=
                        args.compact_terminal_scan_worst,
                        compact_post_clear_worst=
                        args.compact_post_clear_worst,
                        compact_joint_ring_route=
                        args.compact_joint_ring_route,
                        compact_joint_ring_max_known=
                        args.compact_joint_ring_max_known,
                        compact_joint_ring_min_stops=
                        args.compact_joint_ring_min_stops,
                        compact_joint_ring_active_radius=
                        args.compact_joint_ring_active_radius,
                        compact_joint_ring_active_attempts=
                        args.compact_joint_ring_active_attempts,
                        compact_joint_ring_min_directions=
                        args.compact_joint_ring_min_directions,
                        compact_joint_ring_service_worst=
                        args.compact_joint_ring_service_worst,
                        compact_joint_ring_or_opt=args.compact_joint_ring_or_opt,
                        compact_joint_clear_witness=
                        args.compact_joint_clear_witness,
                        compact_joint_clear_witness_useful_only=
                        args.compact_joint_clear_witness_useful_only,
                        compact_joint_clear_witness_max_unknown=
                        args.compact_joint_clear_witness_max_unknown,
                        compact_joint_anchor_substitution=
                        args.compact_joint_anchor_substitution,
                        compact_joint_anchor_substitution_max_unknown=
                        args.compact_joint_anchor_substitution_max_unknown,
                        compact_service_certificate=
                        args.compact_service_certificate,
                        compact_service_certificate_radius=
                        args.compact_service_certificate_radius,
                        compact_service_certificate_max_services=
                        args.compact_service_certificate_max_services,
                        compact_service_certificate_depth=
                        args.compact_service_certificate_depth,
                        compact_service_certificate_active_candidates=
                        args.compact_service_certificate_active_candidates,
                        compact_service_certificate_rollout=
                        args.compact_service_certificate_rollout,
                        compact_service_certificate_min_saving_m=
                        args.compact_service_certificate_min_saving,
                        compact_tail_rollout_budget=
                        args.compact_tail_rollout_budget,
                        compact_tail_rollout_worlds=
                        args.compact_tail_rollout_worlds,
                        compact_tail_rollout_candidates=
                        args.compact_tail_rollout_candidates,
                        compact_tail_rollout_margin_s=
                        args.compact_tail_rollout_margin,
                        compact_tail_rollout_min_win_fraction=
                        args.compact_tail_rollout_min_win_fraction,
                        compact_tail_rollout_objective=
                        args.compact_tail_rollout_objective,
                        compact_tail_rollout_step_limit=
                        args.compact_tail_rollout_step_limit,
                        compact_coverage_rollout_budget=
                        args.compact_coverage_rollout_budget,
                        compact_coverage_rollout_worlds=
                        args.compact_coverage_rollout_worlds,
                        compact_coverage_rollout_candidates=
                        args.compact_coverage_rollout_candidates,
                        compact_coverage_rollout_points=
                        args.compact_coverage_rollout_points,
                        compact_coverage_rollout_service_scan=
                        args.compact_coverage_rollout_service_scan,
                        compact_coverage_rollout_service_channels=
                        args.compact_coverage_rollout_service_channels,
                        compact_coverage_rollout_post_service_scan=
                        args.compact_coverage_rollout_post_service_scan,
                        compact_coverage_rollout_margin_s=
                        args.compact_coverage_rollout_margin,
                        compact_coverage_rollout_min_win_fraction=
                        args.compact_coverage_rollout_min_win_fraction,
                        compact_coverage_branch_actions=
                        args.compact_coverage_branch_actions,
                        compact_coverage_branch_detour_m=
                        args.compact_coverage_branch_detour,
                        compact_coverage_rollout_step_limit=
                        args.compact_coverage_rollout_step_limit,
                        compact_adaptive_ring_points=
                        args.compact_adaptive_ring_points,
                        compact_adaptive_ring_radius=
                        args.compact_adaptive_ring_radius,
                        compact_adaptive_ring_known_max=
                        args.compact_adaptive_ring_known_max,
                        compact_adaptive_ring_rollout=
                        args.compact_adaptive_ring_rollout)
                report = runtime.run_case('Q3', seed, n, args.scenario, cls,
                                          target, cfg)
                runner = AuditingRunner.LAST
                m = report['metrics']
                row = dict(policy=name, n=n, seed=seed,
                           complete=bool(report['complete']),
                           verifier=bool(report['verifier_all_ok']),
                           cleared=m['cleared_count'],
                           total_s=m['T_total_virtual'],
                           seconds_per_source=m['t_per_source_s'],
                           move_s=m['T_move'], measure_s=m['T_measure'],
                           switch_s=m['T_switch'], clear_s=m['T_clear'],
                           wall_s=m['wall_clock_s'], audit=dict(runner.audit),
                           truth_checks=runner.truth_checks,
                           truth_failures=runner.truth_failures,
                           anomalies=list(runner.scheduler.anomalies))
                row['constraints'] = {str(cid): ch.constraint_stats
                    for cid, ch in runner.ks.channels.items()
                    if hasattr(ch, 'constraint_stats')}
                row['search'] = getattr(runner.scheduler, 'segment_stats', {})
                if name in ('macro', 'compact'):
                    (target / 'segment_search.json').write_text(json.dumps(
                        runner.scheduler.segment_log, indent=2), encoding='utf-8')
                if name == 'compact':
                    row['compact'] = dict(runner.scheduler.compact_stats)
                    row['fusion'] = dict(runner.scheduler.fusion_stats)
                    row['tail_rollout'] = dict(
                        runner.scheduler.tail_rollout_stats)
                    row['coverage_rollout'] = dict(
                        runner.scheduler.coverage_rollout_stats)
                    (target / 'stop_fusion.json').write_text(json.dumps(
                        {'stats': runner.scheduler.fusion_stats,
                         'decisions': runner.scheduler.fusion_log}, indent=2),
                        encoding='utf-8')
                    (target / 'tail_rollout.json').write_text(json.dumps(
                        {'stats': runner.scheduler.tail_rollout_stats,
                         'decisions': runner.scheduler.tail_rollout_log}, indent=2),
                        encoding='utf-8')
                    (target / 'coverage_rollout.json').write_text(json.dumps(
                        {'stats': runner.scheduler.coverage_rollout_stats,
                         'decisions': runner.scheduler.coverage_rollout_log},
                        indent=2), encoding='utf-8')
                rows.append(row)
                completed.add((n, seed, name))
                result_path.write_text(json.dumps(
                    dict(args=vars(args), code_sha256=hashes, rows=rows),
                    indent=2), encoding='utf-8')
                print(f'Q3/{n} seed={seed} {name}: '
                      f'{row["seconds_per_source"]:.3f} s/src '
                      f'wall={row["wall_s"]:.2f}s '
                      f'complete={row["complete"]} verifier={row["verifier"]} '
                      f'audit={row["audit"]} truth_fail={len(row["truth_failures"])} '
                      f'search={row["search"]}',
                      flush=True)
                if (not row['complete'] or not row['verifier'] or
                        row['cleared'] != n or row['audit']['mismatch'] or
                        row['truth_failures'] or any(
                            'inconsisten' in a or 'rejected' in a
                            for a in row['anomalies'])):
                    return 1
    for n in args.counts:
        values = {name: [r['seconds_per_source'] for r in rows
                         if r['n'] == n and r['policy'] == name]
                  for name in args.policies}
        for name, vals in values.items():
            print(f'Q3/{n} {name}: mean={statistics.mean(vals):.3f}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
