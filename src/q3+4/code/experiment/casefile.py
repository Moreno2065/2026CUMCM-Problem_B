# -*- coding: utf-8 -*-
"""冻结案例文件体系（Addendum D.3/D.4, B.3）。

案例 JSON（单案例）字段：
    format_version, case_id, case_seed, question ("q3"|"q4"),
    source_count, channels, positions, receive_radii,
    directions（全向源为 null）, scenario（构造族标签）,
    error_field_type（random_fixed|boundary|structured）,
    error_field_version

案例集 JSON（如 tune_q3.json）字段：
    set_name, purpose, question, generated_at, cases: [case, ...]

确定性：generate_case 完全由 case_seed 决定；同一案例文件经
SyntheticSimulator.from_case 构造 ⇒ 完全相同的局（含误差场，
因误差场参数由 case_seed 确定性派生）。

目录隔离（Addendum B.3）：tune/ 调参；ablation/ 消融；stress/ 失败模式；
holdout/ 冻结后验证。种子段互不相交（见 _SEED_BLOCKS），case_id 全局唯一。
"""

import hashlib
import json
import math
import os
import random

from geometry import constants as C
from .simulator import ERROR_FIELD_TYPES, ERROR_FIELD_VERSION, make_sources

CASE_FORMAT_VERSION = 1

# 场景族 → make_sources 的 scenario 参数
GENERATIVE_SCENARIOS = ("random", "boundary", "dense", "sparse",
                        "edge_facing", "mixed")
# 显式构造族（generate_case 内手工构造，不经 make_sources）
EXPLICIT_SCENARIOS = ("r_eff_low", "r_eff_high", "parallel_bearing",
                      "near_early", "empty_channels", "rim")

# 种子段：四集互不相交
_SEED_BLOCKS = {"tune": 100000, "ablation": 200000, "stress": 300000,
                "holdout": 400000}

# case_id is an experiment label and may legitimately change when a case is
# copied into a new data block.  All fields below affect the simulated case;
# in particular case_seed is retained because it determines the fixed error
# field even when the source geometry happens to match.
CANONICAL_CASE_FIELDS = (
    "format_version", "case_seed", "question", "source_count", "channels",
    "positions", "receive_radii", "directions", "scenario",
    "error_field_type", "error_field_version",
)


# ---------------------------------------------------------------------------
# 单案例生成
# ---------------------------------------------------------------------------

def _case_from_sources(question, case_seed, case_id, scenario, sources,
                       error_field_type):
    return {
        "format_version": CASE_FORMAT_VERSION,
        "case_id": case_id,
        "case_seed": int(case_seed),
        "question": question,
        "source_count": len(sources),
        "channels": [s.channel for s in sources],
        "positions": [[s.x, s.y] for s in sources],
        "receive_radii": [s.r_eff for s in sources],
        "directions": [s.orientation if s.directional else None
                       for s in sources],
        "scenario": scenario,
        "error_field_type": error_field_type,
        "error_field_version": ERROR_FIELD_VERSION,
    }


class _Src:
    """显式构造族的轻量源记录（与 simulator.Source 同字段）。"""

    def __init__(self, channel, x, y, r_eff, directional, orientation):
        self.channel = channel
        self.x = float(x)
        self.y = float(y)
        self.r_eff = float(r_eff)
        self.directional = bool(directional)
        self.orientation = float(orientation) % 360.0


def _explicit_sources(question, rng, scenario, n_sources):
    """显式构造族（D.3 中 make_sources 场景参数无法表达的情形）。"""
    R = C.OMEGA_RADIUS

    def rand_pos(r_lo=0.0, r_hi=1.0):
        rr = R * math.sqrt(rng.uniform(r_lo, r_hi))
        aa = rng.uniform(0, 2 * math.pi)
        return (rr * math.cos(aa), rr * math.sin(aa))

    def orient_for(x, y):
        if question == "q3":
            return False, 0.0
        return True, rng.uniform(0.0, 360.0)

    n = n_sources or 10
    srcs = []
    if scenario in ("r_eff_low", "r_eff_high"):
        # 全部源 R_eff 贴近下界 1000 / 上界 1500
        base, spread = (C.R_EFF_MIN, 20.0) if scenario == "r_eff_low" \
            else (C.R_EFF_MAX - 20.0, 20.0)
        chans = rng.sample(range(1, C.NUM_CHANNELS + 1), n)
        for ch in chans:
            x, y = rand_pos()
            d, o = orient_for(x, y)
            srcs.append(_Src(ch, x, y, base + rng.uniform(0.0, spread),
                             d, o))
    elif scenario == "parallel_bearing":
        # 近平行 bearing：两个源沿同一射线方向远近排列，从原点附近观测
        # 两者 bearing 之差 < 1°（落在 ±1° 误差界内，交会极度病态）
        ang = rng.uniform(0, 2 * math.pi)
        ca, sa = math.cos(ang), math.sin(ang)
        p1 = (1000.0 * ca + rng.uniform(-3, 3), 1000.0 * sa
              + rng.uniform(-3, 3))
        p2 = (1450.0 * ca + rng.uniform(-3, 3), 1450.0 * sa
              + rng.uniform(-3, 3))
        chans = rng.sample(range(1, C.NUM_CHANNELS + 1), max(n, 4))
        special = [p1, p2]
        for i, ch in enumerate(chans[:n]):
            x, y = special[i] if i < 2 else rand_pos()
            d, o = orient_for(x, y)
            srcs.append(_Src(ch, x, y,
                             rng.uniform(C.R_EFF_MIN, C.R_EFF_MAX), d, o))
    elif scenario == "near_early":
        # near 提前触发：一个源放在原点 5 m 内（首个停点扫描即 near）
        chans = rng.sample(range(1, C.NUM_CHANNELS + 1), n)
        for i, ch in enumerate(chans):
            if i == 0:
                a = rng.uniform(0, 2 * math.pi)
                r = rng.uniform(1.0, C.NEAR_THRESHOLD - 0.5)
                x, y = r * math.cos(a), r * math.sin(a)
            else:
                x, y = rand_pos()
            d, o = orient_for(x, y)
            srcs.append(_Src(ch, x, y,
                             rng.uniform(C.R_EFF_MIN, C.R_EFF_MAX), d, o))
    elif scenario == "empty_channels":
        # 大量空频道：10 源占 20 频道（一半频道恒空）
        chans = rng.sample(range(1, C.NUM_CHANNELS + 1), 10)
        for ch in chans:
            x, y = rand_pos()
            d, o = orient_for(x, y)
            srcs.append(_Src(ch, x, y,
                             rng.uniform(C.R_EFF_MIN, C.R_EFF_MAX), d, o))
    elif scenario == "rim":
        # 边界源（D.3 严格口径）：全部源距原点 ≥ 1700 m
        chans = rng.sample(range(1, C.NUM_CHANNELS + 1), n)
        r2_lo = (1700.0 / R) ** 2
        for ch in chans:
            rr = R * math.sqrt(rng.uniform(r2_lo, 1.0))
            aa = rng.uniform(0, 2 * math.pi)
            x, y = rr * math.cos(aa), rr * math.sin(aa)
            d, o = orient_for(x, y)
            srcs.append(_Src(ch, x, y,
                             rng.uniform(C.R_EFF_MIN, C.R_EFF_MAX), d, o))
    else:  # pragma: no cover
        raise ValueError("unknown explicit scenario %r" % scenario)
    return srcs


def generate_case(question, case_seed, case_id=None, scenario="random",
                  n_sources=None, error_field_type="random_fixed"):
    """按 seed 确定性生成案例 dict。

    question: "q3"|"q4"；scenario: 场景族标签（GENERATIVE_SCENARIOS 走
    simulator.make_sources 的既有生成器，EXPLICIT_SCENARIOS 手工构造）。
    """
    question = question.lower()
    if question not in ("q3", "q4"):
        raise ValueError("question must be 'q3' or 'q4'")
    if error_field_type not in ERROR_FIELD_TYPES:
        raise ValueError("error_field_type must be one of %r"
                         % (ERROR_FIELD_TYPES,))
    case_seed = int(case_seed)
    if case_id is None:
        case_id = "%s_%s_%06d" % (question, scenario, case_seed)
    mode = question.upper()
    if scenario in EXPLICIT_SCENARIOS:
        rng = random.Random(case_seed)
        sources = _explicit_sources(question, rng, scenario, n_sources)
    elif scenario in GENERATIVE_SCENARIOS:
        sources = make_sources(mode, case_seed, n_sources, scenario)
    else:
        raise ValueError("unknown scenario %r" % scenario)
    return _case_from_sources(question, case_seed, case_id, scenario,
                              sources, error_field_type)


# ---------------------------------------------------------------------------
# 校验与读写
# ---------------------------------------------------------------------------

def validate_case(case):
    """结构校验；非法抛 ValueError。"""
    req = ("case_id", "case_seed", "question", "source_count", "channels",
           "positions", "receive_radii", "directions",
           "error_field_type", "error_field_version")
    for k in req:
        if k not in case:
            raise ValueError("case missing field %r" % k)
    if case["question"] not in ("q3", "q4"):
        raise ValueError("question must be 'q3' or 'q4'")
    n = case["source_count"]
    for k in ("channels", "positions", "receive_radii", "directions"):
        if len(case[k]) != n:
            raise ValueError("field %r length != source_count" % k)
    if case["error_field_type"] not in ERROR_FIELD_TYPES:
        raise ValueError("bad error_field_type %r"
                         % case["error_field_type"])
    for (x, y), r in zip(case["positions"], case["receive_radii"]):
        if math.hypot(x, y) > C.OMEGA_RADIUS + 1e-6:
            raise ValueError("position outside Ω: %r" % ((x, y),))
        if not (C.R_EFF_MIN - 1e-6 <= r <= C.R_EFF_MAX + 1e-6):
            raise ValueError("receive radius out of [1000,1500]: %r" % r)
    if case["question"] == "q3" and any(d is not None
                                        for d in case["directions"]):
        raise ValueError("q3 sources must be omnidirectional (null dir)")
    return True


def save_case(case, path):
    validate_case(case)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(case, f, ensure_ascii=False, indent=1,
                  sort_keys=True)
        f.write("\n")
    return path


def load_case(path):
    with open(path, "r", encoding="utf-8") as f:
        case = json.load(f)
    validate_case(case)
    return case


def save_case_set(set_name, purpose, question, cases, path):
    for c in cases:
        validate_case(c)
        if c["question"] != question:
            raise ValueError("case %r question != set question %r"
                             % (c["case_id"], question))
    obj = {"set_name": set_name, "purpose": purpose, "question": question,
           "generated_at": _now_iso(), "cases": cases}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return path


def load_case_set(path):
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    for c in obj["cases"]:
        validate_case(c)
    return obj


def canonical_case_payload(case):
    """Return case content used for cross-split identity checks.

    ``case_id`` is intentionally excluded because it is a reporting label,
    not simulator input.  The returned mapping is JSON-serializable and keeps
    the exact numeric values loaded from the case file.
    """
    validate_case(case)
    return {key: case[key] for key in CANONICAL_CASE_FIELDS}


def canonical_case_hash(case):
    """Return a stable SHA-256 hash for the simulator-relevant case content."""
    encoded = json.dumps(canonical_case_payload(case), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")) \
        .encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def audit_case_hash_isolation(named_paths):
    """Find duplicate canonical cases across named data splits.

    ``named_paths`` maps a split name (for example ``train`` or ``holdout``)
    to one path or a sequence of case-set JSON paths.  The function is
    read-only and returns evidence rather than silently rewriting old data.
    """
    if not isinstance(named_paths, dict) or not named_paths:
        raise ValueError("named_paths must be a non-empty mapping")
    locations_by_hash = {}
    total_cases = 0
    for split, paths in named_paths.items():
        if isinstance(paths, (str, bytes, os.PathLike)):
            paths = [paths]
        for path in paths:
            with open(os.fspath(path), "r", encoding="utf-8") as f:
                payload = json.load(f)
            cases = payload.get("cases") if isinstance(payload, dict) \
                else None
            if cases is None:
                cases = [payload]
            for index, case in enumerate(cases):
                digest = canonical_case_hash(case)
                locations_by_hash.setdefault(digest, []).append({
                    "split": str(split),
                    "path": os.path.abspath(os.fspath(path)),
                    "index": index,
                    "case_id": case["case_id"],
                    "case_seed": case["case_seed"],
                })
                total_cases += 1
    duplicates = [
        {"hash": digest, "locations": locations}
        for digest, locations in sorted(locations_by_hash.items())
        if len(locations) > 1
    ]
    cross_split_duplicates = [item for item in duplicates
                             if len({loc["split"]
                                     for loc in item["locations"]}) > 1]
    within_split_duplicates = [item for item in duplicates
                               if len({loc["split"]
                                       for loc in item["locations"]}) == 1]
    return {
        "ok": not duplicates,
        "cross_split_ok": not cross_split_duplicates,
        "total_cases": total_cases,
        "unique_hashes": len(locations_by_hash),
        "duplicate_hashes": [item["hash"] for item in duplicates],
        "cross_split_duplicate_hashes": [item["hash"] for item in
                                         cross_split_duplicates],
        "within_split_duplicate_hashes": [item["hash"] for item in
                                          within_split_duplicates],
        "duplicates": duplicates,
    }


def _now_iso():
    import datetime
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 四个隔离案例集（Addendum B.3 / D.3）
# ---------------------------------------------------------------------------

def _seed(block, i, seed_offset=0):
    return _SEED_BLOCKS[block] + int(seed_offset) + i


def _tune_cases(question, seed_offset=0, case_id_prefix=""):
    """tune 集（C 类参数筛选用）：代表性常规场景，6 案例。"""
    blk = "tune"
    specs = [("random", 10), ("random", 12), ("dense", 10),
             ("sparse", 10), ("boundary", 10), ("random", 16)]
    if question == "q4":
        specs[5] = ("mixed", 14)
    return [generate_case(question, _seed(blk, i, seed_offset),
                          case_id="%stune_%s_%02d"
                                  % (case_id_prefix, question, i + 1),
                          scenario=sc, n_sources=n)
            for i, (sc, n) in enumerate(specs)]


def _ablation_cases(question, seed_offset=0, case_id_prefix=""):
    """ablation 集（模块贡献，matched-case）：与 tune 同族不同种子。"""
    blk = "ablation"
    specs = [("random", 10), ("random", 12), ("dense", 10),
             ("sparse", 10), ("boundary", 10), ("random", 16)]
    if question == "q4":
        specs[5] = ("mixed", 14)
    return [generate_case(question, _seed(blk, i, seed_offset),
                          case_id="%sablation_%s_%02d"
                                  % (case_id_prefix, question, i + 1),
                          scenario=sc, n_sources=n)
            for i, (sc, n) in enumerate(specs)]


def _stress_cases(question, seed_offset=0, case_id_prefix=""):
    """stress 集（失败模式，D.3 场景族全覆盖）。"""
    blk = "stress"

    def mk(i, sc, n=None, ef="random_fixed"):
        return generate_case(question, _seed(blk, i, seed_offset),
                             case_id="%sstress_%s_%02d_%s"
                                     % (case_id_prefix, question, i + 1, sc),
                             scenario=sc, n_sources=n, error_field_type=ef)

    cases = [
        mk(0, "random", 10),                    # 10 源
        mk(1, "random", 16),                    # 16 源（题设上限）
        mk(2, "rim", 10),                       # 边界源（全部 ≥1700 m）
        mk(3, "dense", 12),                     # 空间聚簇
        mk(4, "sparse", 10),                    # 分散源
        mk(5, "r_eff_low", 10),                 # R_eff 全接近 1000
        mk(6, "r_eff_high", 10),                # R_eff 全接近 1500
        mk(7, "parallel_bearing", 10),          # 近平行 bearing 构造
        mk(8, "near_early", 10),                # near 提前触发
        mk(9, "empty_channels", 10),            # 大量空频道（10 源 20 频道）
        mk(10, "random", 12, "boundary"),       # 边界/对抗误差场
        mk(11, "random", 12, "structured"),     # 空间相关低频误差场
    ]
    if question == "q4":
        cases.insert(5, mk(12, "edge_facing", 12))  # Q4 不利定向
        cases.append(mk(13, "edge_facing", 10, "boundary"))  # 定向+对抗场
    return cases


def _holdout_cases(question, seed_offset=0, case_id_prefix=""):
    """holdout 集（冻结后验证；调参与消融禁止触碰）。"""
    blk = "holdout"
    specs = [("random", 10), ("random", 13), ("dense", 11),
             ("sparse", 12), ("boundary", 12), ("random", 16)]
    if question == "q4":
        specs.append(("edge_facing", 10))
    return [generate_case(question, _seed(blk, i, seed_offset),
                          case_id="%sholdout_%s_%02d"
                                  % (case_id_prefix, question, i + 1),
                          scenario=sc, n_sources=n)
            for i, (sc, n) in enumerate(specs)]


_PURPOSES = {
    "tune": "C 类参数（tau）筛选专用（Addendum B.3）；禁止用于消融/验证",
    "ablation": "四组核心消融 matched-case 专用（Addendum C/D.4）",
    "stress": "失败模式与对抗工况（Addendum D.3 场景族全覆盖）",
    "holdout": "FROZEN_CONFIG 冻结后的最终验证；调参与消融禁止触碰",
}


def generate_all_case_sets(out_dir, tag=None, seed_offset=0):
    """生成 tune/ablation/stress/holdout 四集 × q3/q4 到 out_dir。

    tag 非空时写入 out_dir/tag/ 并给每个 case_id、set_name 加同名
    前缀；seed_offset 同时平移四个保留的互不重叠种子段，供新模型版本
    生成从未暴露的评估语料。

    返回 {子目录: [写出的文件路径]}。每个子目录带 manifest.json。
    """
    tag = str(tag).strip() if tag is not None else ""
    if tag and (not tag.replace("_", "").isalnum()):
        raise ValueError("tag must contain only letters, digits, and underscores")
    seed_offset = int(seed_offset)
    tag_prefix = tag + "_" if tag else ""
    root = os.path.join(out_dir, tag) if tag else out_dir
    builders = {"tune": _tune_cases, "ablation": _ablation_cases,
                "stress": _stress_cases, "holdout": _holdout_cases}
    written = {}
    for name, builder in builders.items():
        sub = os.path.join(root, name)
        paths = []
        manifest_cases = []
        for q in ("q3", "q4"):
            cases = builder(q, seed_offset=seed_offset,
                            case_id_prefix=tag_prefix)
            fn = os.path.join(sub, "%s_%s.json" % (name, q))
            save_case_set("%s%s_%s" % (tag_prefix, name, q),
                          _PURPOSES[name], q,
                          cases, fn)
            paths.append(fn)
            manifest_cases.append({
                "file": os.path.basename(fn),
                "question": q,
                "n_cases": len(cases),
                "case_ids": [c["case_id"] for c in cases],
                "scenarios": sorted({c["scenario"] for c in cases}),
                "error_field_types": sorted({c["error_field_type"]
                                             for c in cases}),
            })
        manifest = {
            "set": name,
            "purpose": _PURPOSES[name],
            "generated_at": _now_iso(),
            "seed_block": _SEED_BLOCKS[name] + seed_offset,
            "seed_offset": seed_offset,
            "tag": tag or None,
            "isolation": "seed blocks are pairwise disjoint; case_id 全局唯一；"
                         "四集无交集",
            "case_files": manifest_cases,
        }
        mp = os.path.join(sub, "manifest.json")
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
            f.write("\n")
        paths.append(mp)
        written[name] = paths
    return written


def generate_q3_ml_case_sets(out_dir, train_count=500, explore_count=1000,
                             holdout_count=1000, seed_start=2000000,
                             reference_paths=None, tag=None):
    """Generate isolated Q3 ML train/explore/holdout case files.

    The three splits use disjoint one-million-wide seed bands.  ``reference``
    paths are optional historical case files; when supplied, any canonical
    hash collision with a new split raises after the collision evidence is
    recorded in the exception.  Existing files are never overwritten by this
    function unless the caller explicitly chooses the same output directory.
    """
    counts = {
        "train": int(train_count),
        "explore": int(explore_count),
        "holdout": int(holdout_count),
    }
    if any(value <= 0 for value in counts.values()):
        raise ValueError("Q3 ML split counts must be positive")
    seed_start = int(seed_start)
    stride = 1000000
    if max(counts.values()) >= stride:
        raise ValueError("each Q3 ML split must fit within its seed band")
    tag = str(tag).strip() if tag is not None else ""
    if tag and not tag.replace("_", "").isalnum():
        raise ValueError("tag must contain only letters, digits, and underscores")
    root = os.path.join(os.fspath(out_dir), tag) if tag else os.fspath(out_dir)

    scenario_plans = {
        "train": (("random", 10, "random_fixed"),
                   ("dense", 12, "random_fixed"),
                   ("sparse", 10, "random_fixed"),
                   ("boundary", 12, "random_fixed")),
        "explore": (("rim", 10, "random_fixed"),
                    ("r_eff_low", 10, "random_fixed"),
                    ("r_eff_high", 10, "random_fixed"),
                    ("parallel_bearing", 10, "random_fixed"),
                    ("near_early", 10, "random_fixed"),
                    ("empty_channels", 10, "random_fixed"),
                    ("random", 12, "boundary"),
                    ("random", 12, "structured")),
        "holdout": (("random", 11, "random_fixed"),
                     ("dense", 13, "random_fixed"),
                     ("sparse", 12, "random_fixed"),
                     ("boundary", 12, "random_fixed"),
                     ("rim", 10, "structured")),
    }
    written = {}
    manifest_splits = {}
    for band, (split, count) in enumerate(counts.items()):
        cases = []
        plan = scenario_plans[split]
        for index in range(count):
            scenario, n_sources, error_field = plan[index % len(plan)]
            seed = seed_start + band * stride + index
            prefix = (tag + "_" if tag else "")
            case = generate_case(
                "q3", seed,
                case_id="%sq3_ml_%s_%05d" % (prefix, split, index + 1),
                scenario=scenario, n_sources=n_sources,
                error_field_type=error_field)
            cases.append(case)
        path = os.path.join(root, "%s_q3.json" % split)
        save_case_set("%sq3_ml_%s" %
                      (tag + "_" if tag else "", split),
                      "Q3 ML %s split; canonical hash isolated" % split,
                      "q3", cases, path)
        hashes = [canonical_case_hash(case) for case in cases]
        written[split] = [path]
        manifest_splits[split] = {
            "file": os.path.basename(path),
            "question": "q3",
            "n_cases": len(cases),
            "case_hashes": hashes,
            "seed_start": cases[0]["case_seed"],
            "seed_end": cases[-1]["case_seed"],
        }

    new_isolation = audit_case_hash_isolation(written)
    isolation_inputs = dict(written)
    if reference_paths:
        isolation_inputs = {"reference": list(reference_paths),
                            **isolation_inputs}
    isolation = audit_case_hash_isolation(isolation_inputs)
    if not new_isolation["ok"] or not isolation["cross_split_ok"]:
        raise ValueError("Q3 ML case hash isolation failed: %s" %
                         json.dumps({"new": new_isolation,
                                     "combined": isolation},
                                    ensure_ascii=False))
    root_manifest = {
        "format_version": 1,
        "generated_at": _now_iso(),
        "seed_start": seed_start,
        "split_seed_stride": stride,
        "tag": tag or None,
        "splits": manifest_splits,
        "isolation": {
            "ok": new_isolation["ok"] and isolation["cross_split_ok"],
            "cross_split_ok": isolation["cross_split_ok"],
            "new_split_ok": new_isolation["ok"],
            "total_cases": new_isolation["total_cases"],
            "unique_hashes": new_isolation["unique_hashes"],
            "duplicate_hashes": new_isolation["duplicate_hashes"],
        },
    }
    if reference_paths:
        root_manifest["reference_case_files"] = [
            os.path.abspath(os.fspath(path)) for path in reference_paths]
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(root_manifest, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return written
