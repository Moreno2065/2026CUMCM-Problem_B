"""One-off trajectory analysis: bucketed movement, measure mix, full-info bounds."""
import csv, math, json, sys
from collections import defaultdict


def analyze(path, gt_path, label):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    by_action = defaultdict(lambda: [0.0, 0])
    prev = None
    total_move = 0.0
    for r in rows:
        x, y = float(r["x"]), float(r["y"])
        if prev is not None:
            d = math.hypot(x - prev[0], y - prev[1])
            if d > 0:
                by_action[r["action"]][0] += d
                by_action[r["action"]][1] += 1
                total_move += d
        prev = (x, y)
    print("== %s ==" % label)
    print("total move %.1f m" % total_move)
    for a, (d, n) in sorted(by_action.items(), key=lambda kv: -kv[1][0]):
        print("   %-8s %9.1f m  (%d legs)" % (a, d, n))
    res = defaultdict(int)
    for r in rows:
        if r["action"] == "measure":
            res[r["result"]] += 1
    print("measure results:", dict(res))
    cl = [r for r in rows if r["action"] == "clear"]
    print("clears: %d, success: %d" % (len(cl), sum(1 for r in cl if r["result"] == "success")))
    gt = json.load(open(gt_path, encoding="utf-8"))
    pts = [(s["x"], s["y"]) for s in gt]
    origin = (0.0, 0.0)

    def w(a, b):
        if a is origin:
            return max(0.0, math.hypot(b[0], b[1]) - 20.0)
        if b is origin:
            return max(0.0, math.hypot(a[0], a[1]) - 20.0)
        return max(0.0, math.hypot(a[0] - b[0], a[1] - b[1]) - 40.0)

    nodes = [origin] + pts
    n = len(nodes)
    in_mst = [False] * n
    key = [float("inf")] * n
    key[0] = 0.0
    tot = 0.0
    for _ in range(n):
        u = min((i for i in range(n) if not in_mst[i]), key=lambda i: key[i])
        in_mst[u] = True
        tot += key[u]
        for v in range(n):
            if not in_mst[v]:
                k = w(nodes[u], nodes[v])
                if k < key[v]:
                    key[v] = k
    print("MST lower bound 5N+M/5 = %.1f s  (M=%.1f m)" % (5 * len(pts) + tot / 5.0, tot))
    rem = list(range(1, n))
    cur = 0
    L = 0.0
    while rem:
        j = min(rem, key=lambda i: math.hypot(
            nodes[cur][0] - nodes[i][0], nodes[cur][1] - nodes[i][1]))
        L += math.hypot(nodes[cur][0] - nodes[j][0], nodes[cur][1] - nodes[j][1])
        cur = j
        rem.remove(j)
    print("NN open route 5N+L/5 = %.1f s (L=%.1f m)" % (5 * len(pts) + L / 5.0, L))


if __name__ == "__main__":
    analyze(sys.argv[1], sys.argv[2], sys.argv[3])
