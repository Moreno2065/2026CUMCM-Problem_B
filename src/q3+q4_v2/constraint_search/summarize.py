"""Summarize paired measured episodes; never optimize parameters on evaluation."""
import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def percentile(values, q):
    vals = sorted(values)
    at = (len(vals) - 1) * q
    lo = int(at)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] * (hi - at) + vals[hi] * (at - lo) if hi != lo else vals[lo]


def summarize(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    rows = data['rows']
    base = {(r['n'], r['seed']): r for r in rows if r['policy'] == 'production'}
    summaries = []
    for n in sorted({r['n'] for r in rows}):
        policies = sorted({r['policy'] for r in rows if r['n'] == n},
                          key=lambda name: (name != 'production', name))
        for policy in policies:
            group = [r for r in rows if r['n'] == n and r['policy'] == policy]
            if not group:
                continue
            values = [r['seconds_per_source'] for r in group]
            paired = [(r, base.get((n, r['seed']))) for r in group]
            paired = [(r, b) for r, b in paired if b is not None]
            deltas = [r['seconds_per_source'] - b['seconds_per_source']
                      for r, b in paired]
            baselines = [b['seconds_per_source'] for _, b in paired]
            stats = dict(n=n, policy=policy, cases=len(group),
                         mean=statistics.mean(values),
                         mean_delta=(statistics.mean(deltas) if deltas else None),
                         percent_delta=(100 * statistics.mean(deltas) /
                                        statistics.mean(baselines)
                                        if deltas else None),
                         worst=max(values), p90=percentile(values, .9),
                         worse=sum(d > 1e-6 for d in deltas),
                         worst_paired_delta=max(deltas) if deltas else None,
                         regressions_above_10pct=sum(d > .1*b for d, b in zip(deltas, baselines)),
                         max_wall_s=max(r['wall_s'] for r in group))
            for key in ('move_s', 'measure_s', 'switch_s', 'clear_s'):
                stats[key+'_delta'] = (statistics.mean(
                    r[key] - b[key] for r, b in paired) if paired else None)
            summaries.append(stats)
    audit = dict(episodes=len(rows),
                 all_clear=all(r['complete'] and r['cleared'] == r['n'] for r in rows),
                 all_verifier=all(r['verifier'] for r in rows),
                 matched=sum(r['audit']['matched'] for r in rows),
                 truncated=sum(r['audit']['truncated'] for r in rows),
                 mismatch=sum(r['audit']['mismatch'] for r in rows),
                 truth_checks=sum(r['truth_checks'] for r in rows),
                 truth_failures=sum(len(r['truth_failures']) for r in rows))
    return dict(source=str(path), summaries=summaries, audit=audit,
                code_sha256=data['code_sha256'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('tags', nargs='+')
    args = parser.parse_args()
    result = {}
    for tag in args.tags:
        folder = ROOT / 'tuning_runs' / 'constraint_search' / tag
        report = summarize(folder / 'results.json')
        (folder / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        result[tag] = report
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
