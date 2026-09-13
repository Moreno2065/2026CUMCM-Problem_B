"""Paired complete-episode audit; never use world truth for action selection."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'baseline' / 'code'))
sys.path.insert(0, str(ROOT / 'tools'))

import runtime
import production
from check_plan_execution import AuditingRunner
from learned_search.scheduler import LearnedSearchScheduler
from belief_rollout.scheduler import BeliefRolloutScheduler


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--seeds', nargs='+', type=int, default=[101, 303, 505])
    p.add_argument('--cases', nargs='+', default=['Q3:16', 'Q4:16'])
    p.add_argument('--worlds', type=int, default=4)
    p.add_argument('--candidates', type=int, default=9)
    p.add_argument('--period', type=int, default=3)
    p.add_argument('--budget', type=float, default=240.0)
    p.add_argument('--margin', type=float, default=20.0)
    p.add_argument('--min-win-fraction', type=float, default=0.5)
    p.add_argument('--objective', choices=('mean', 'median'), default='mean')
    p.add_argument('--clear-radius', type=float, default=0.0)
    p.add_argument('--clear-candidates', type=int, default=3)
    p.add_argument('--clear-only', action='store_true')
    p.add_argument('--step-limit', type=int, default=300)
    p.add_argument('--disabled', action='store_true')
    p.add_argument('--tag', default='screen')
    args = p.parse_args()
    if not 0.0 <= args.min_win_fraction <= 1.0:
        p.error('--min-win-fraction must be between 0 and 1')
    out = ROOT / 'tuning_runs' / 'belief_rollout' / args.tag
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (ROOT / 'belief_rollout' / 'scheduler.py',
                           ROOT / 'belief_rollout' / 'worlds.py',
                           ROOT / 'production.py', ROOT / 'runtime.py')}
    runtime.V2GameRunner = AuditingRunner
    for case in args.cases:
        mode, n = case.split(':')
        n = int(n)
        for seed in args.seeds:
            for name, cls in [('production', LearnedSearchScheduler),
                              ('rollout', BeliefRolloutScheduler)]:
                cfg = production.scheduler_kwargs(mode)
                if name == 'rollout':
                    cfg.update(br_enabled=not args.disabled,
                               br_worlds=args.worlds, br_candidates=args.candidates,
                               br_period=args.period, br_budget_s=args.budget,
                               br_margin_s=args.margin,
                               br_min_win_fraction=args.min_win_fraction,
                               br_objective=args.objective,
                               br_clear_radius=args.clear_radius,
                               br_clear_candidates=args.clear_candidates,
                               br_clear_only=args.clear_only,
                               br_step_limit=args.step_limit)
                target = out / f'{mode}_{n}_{seed}' / name
                report = runtime.run_case(mode, seed, n,
                                          'random' if mode == 'Q3' else 'mixed',
                                          cls, target, scheduler_kwargs=cfg)
                runner = AuditingRunner.LAST
                m = report['metrics']
                row = {'policy': name, 'mode': mode, 'n': n, 'seed': seed,
                       'complete': bool(report['complete']),
                       'verifier': bool(report['verifier_all_ok']),
                       'seconds_per_source': m['t_per_source_s'],
                       'total_s': m['T_total_virtual'],
                       'move_s': m['T_move'], 'measure_s': m['T_measure'],
                       'switch_s': m['T_switch'], 'clear_s': m['T_clear'],
                       'wall_s': m['wall_clock_s'], 'audit': runner.audit,
                       'search': getattr(runner.scheduler, 'rollout_stats', {})}
                rows.append(row)
                if name == 'rollout':
                    (target / 'rollout_search.json').write_text(json.dumps(
                        runner.scheduler.rollout_log, indent=2), encoding='utf-8')
                print(f'{mode}/{n} seed={seed} {name}: '
                      f'{row["seconds_per_source"]:.3f} s/src '
                      f'wall={row["wall_s"]:.2f}s '
                      f'ok={row["complete"] and row["verifier"]} '
                      f'mismatch={row["audit"]["mismatch"]} '
                      f'search={row["search"]}', flush=True)
                (out / 'results.json').write_text(json.dumps(
                    {'args': vars(args), 'code_sha256': hashes, 'rows': rows},
                    indent=2), encoding='utf-8')
    for case in args.cases:
        mode, n = case.split(':')
        values = {}
        for name in ('production', 'rollout'):
            vals = sorted(r['seconds_per_source'] for r in rows
                          if r['policy'] == name and r['mode'] == mode and
                          r['n'] == int(n))
            values[name] = statistics.mean(vals)
            print(case, name, 'mean=', round(values[name], 3),
                  'max=', round(max(vals), 3))
        print('delta=', round(values['rollout']-values['production'], 3))
    return int(any(not r['complete'] or not r['verifier'] or
                   r['audit']['mismatch'] for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
