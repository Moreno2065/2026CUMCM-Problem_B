"""Reconstruct route structure: group consecutive same-action legs, print timeline."""
import csv, math, sys
from collections import defaultdict


def run(path, label):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    print("== %s ==" % label)
    prev = None
    t = 0.0
    # per-channel counts
    meas_by_ch = defaultdict(int)
    for r in rows:
        if r["action"] == "measure":
            meas_by_ch[r["channel"]] += 1
        if r["action"] in ("measure", "clear") and prev is not None:
            d = math.hypot(float(r["x"]) - prev[0], float(r["y"]) - prev[1])
            if d > 50:
                print("  t=%7.1f  move %6.0f m -> %-8s ch=%s result=%s at (%.0f,%.0f)"
                      % (float(r["virtual_time"]), d, r["action"], r["channel"],
                         r["result"], float(r["x"]), float(r["y"])))
        prev = (float(r["x"]), float(r["y"]))
    print("  measures per channel:", dict(sorted(meas_by_ch.items())))
    # first time each channel becomes direction/near
    first_dir = {}
    for r in rows:
        if r["action"] == "measure" and r["result"] in ("direction", "near"):
            first_dir.setdefault(r["channel"], float(r["virtual_time"]))
    print("  first signal times:", dict(sorted(first_dir.items(), key=lambda kv: kv[1])))


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
