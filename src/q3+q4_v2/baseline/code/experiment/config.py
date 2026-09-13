# -*- coding: utf-8 -*-
"""运行配置（Addendum B/J）：C 类参数暴露 + 配置快照与哈希。

参数分类（Addendum B.1）：
- A 类（题设/定理常量）在 geometry.constants 冻结，不进入本配置；
- B 类（在线决策变量）由策略运行时求解，不进入本配置；
- C 类（允许演练调参的策略参数）目前只有 tau——机会式观测收益阈值：
  ACTIVE 模式下一次（机会式）观测被接受的最小 gain/cost 得分。
  当前隐式值 τ = 0（任何非负收益候选都可参与 max gain/cost 竞争），
  默认配置 tau=0.0 与既有行为逐字节一致。
- policy 模式开关：nbv_mode（"radius"=ΔR_MEC，默认 / "diameter"=ΔD）。

YAML 解析：优先 pyyaml；无 pyyaml 时退化为 JSON 兼容子集（yaml 是
json 超集，无锚点无特性的纯 key: value 文件可手写解析，本仓库
configs/ 下的文件保持该子集可解析）。
"""

import hashlib
import json
import os

try:
    import yaml
    _HAS_YAML = True
except ImportError:  # pragma: no cover - 托管环境有 pyyaml
    yaml = None
    _HAS_YAML = False

MODEL_VERSION = "v2.1"
SPEC_VERSION = "v2.1+addendum"

# C 类参数默认值（= 当前隐式值；改动默认值即改变 mainline 语义，禁止）
DEFAULT_TAU = 0.0
DEFAULT_NBV_MODE = "radius"
NBV_MODES = ("radius", "diameter")

# 配置中允许出现的键（未知键报错，防止调参时写错键名静默失效）
# 消融开关（Addendum C，各只改一个模块；默认值 = mainline 行为）：
#   nbv_rule           : "nbv"（默认，max ΔR_MEC/cost）|
#                        "fixed_geometry"（A1 baseline，固定几何选点）
#   opportunistic_reuse: true（默认，NBV 候选含当前点/中点等机会式停点）|
#                        false（A2 baseline，只保留专门机动候选）
#   channel_scan_mode  : "state_aware"（默认，只扫 UNKNOWN）|
#                        "sweep_all"（A3 baseline，每停点机械扫全部未结频道）|
#                        "useful_sweep"（UNKNOWN + ACTIVE，去重）|
#                        "selective_sweep"（UNKNOWN + 可达 ACTIVE，实验）|
#                        "selective_clear"（所有机会式停点用信息安全筛选，实验）
#   cert_select        : "gain_cost"（默认，max ΔC/cost）|
#                        "nearest"（A4 baseline，最近未访证书点）
#   q4_naive           : false | true（Q4 专项对照：把单次 no_signal 误当
#                        Q3 式 1000 m 圆盘证书——明知不健全，仅供 C.5 对照）
#   q3_ml_ranker       : false | true（Q3 实验支线：离线线性排序器；只重排
#                        已生成的 NBV 候选，不改几何状态或证书判定）
#   q3_ml_model_path   : optional JSON model artifact；缺省使用内置 surrogate
#   active_scan_margin_m: extra distance margin for selective ACTIVE scans
_ALLOWED_KEYS = {"policy", "tau", "nbv_mode", "max_steps",
                 "nbv_rule", "opportunistic_reuse", "channel_scan_mode",
                 "cert_select", "q4_naive", "q4_certificate_layout",
                 "q4_joint_rank", "cert_route_mode",
                 "q4_residual_sparsify", "q3_ml_ranker",
                 "q3_ml_model_path",
                 "active_scan_margin_m"}


class ConfigError(ValueError):
    pass


class MainlineConfig:
    """一局运行的有效配置（mainline 默认值 + 消融 variant 开关）。"""

    NBV_RULES = ("nbv", "fixed_geometry")
    SCAN_MODES = ("state_aware", "sweep_all", "useful_sweep",
                  "selective_sweep", "selective_clear")
    CERT_SELECTS = ("gain_cost", "nearest")
    Q4_CERTIFICATE_LAYOUTS = ("lattice31", "sparse25")
    CERT_ROUTE_MODES = ("greedy", "lookahead2")

    def __init__(self, tau=DEFAULT_TAU, nbv_mode=DEFAULT_NBV_MODE,
                 policy="mainline", max_steps=None,
                 nbv_rule="nbv", opportunistic_reuse=True,
                 channel_scan_mode="state_aware", cert_select="gain_cost",
                 q4_naive=False, q4_certificate_layout="lattice31",
                 q4_joint_rank=False, cert_route_mode="greedy",
                 q4_residual_sparsify=False, q3_ml_ranker=False,
                 q3_ml_model_path=None, active_scan_margin_m=0.0):
        if policy != "mainline":
            raise ConfigError("unknown policy %r (only 'mainline')" % policy)
        if nbv_mode not in NBV_MODES:
            raise ConfigError("nbv_mode must be one of %r" % (NBV_MODES,))
        if nbv_rule not in self.NBV_RULES:
            raise ConfigError("nbv_rule must be one of %r"
                              % (self.NBV_RULES,))
        if channel_scan_mode not in self.SCAN_MODES:
            raise ConfigError("channel_scan_mode must be one of %r"
                              % (self.SCAN_MODES,))
        if cert_select not in self.CERT_SELECTS:
            raise ConfigError("cert_select must be one of %r"
                              % (self.CERT_SELECTS,))
        if q4_certificate_layout not in self.Q4_CERTIFICATE_LAYOUTS:
            raise ConfigError("q4_certificate_layout must be one of %r"
                              % (self.Q4_CERTIFICATE_LAYOUTS,))
        if cert_route_mode not in self.CERT_ROUTE_MODES:
            raise ConfigError("cert_route_mode must be one of %r"
                              % (self.CERT_ROUTE_MODES,))
        tau = float(tau)
        if tau < 0.0:
            raise ConfigError("tau must be >= 0")
        self.policy = policy
        self.tau = tau
        self.nbv_mode = nbv_mode
        self.max_steps = max_steps
        self.nbv_rule = nbv_rule
        self.opportunistic_reuse = bool(opportunistic_reuse)
        self.channel_scan_mode = channel_scan_mode
        self.cert_select = cert_select
        self.q4_naive = bool(q4_naive)
        self.q4_certificate_layout = q4_certificate_layout
        self.q4_joint_rank = bool(q4_joint_rank)
        self.cert_route_mode = cert_route_mode
        self.q4_residual_sparsify = bool(q4_residual_sparsify)
        self.q3_ml_ranker = bool(q3_ml_ranker)
        try:
            active_scan_margin_m = float(active_scan_margin_m)
        except (TypeError, ValueError):
            raise ConfigError("active_scan_margin_m must be >= 0")
        if active_scan_margin_m < 0.0:
            raise ConfigError("active_scan_margin_m must be >= 0")
        self.active_scan_margin_m = active_scan_margin_m
        if q3_ml_model_path is not None and not isinstance(
                q3_ml_model_path, (str, os.PathLike)):
            raise ConfigError("q3_ml_model_path must be a path or null")
        self.q3_ml_model_path = (os.fspath(q3_ml_model_path)
                                 if q3_ml_model_path is not None else None)

    def to_dict(self):
        d = {"policy": self.policy, "tau": self.tau,
             "nbv_mode": self.nbv_mode,
             "nbv_rule": self.nbv_rule,
             "opportunistic_reuse": self.opportunistic_reuse,
             "channel_scan_mode": self.channel_scan_mode,
             "cert_select": self.cert_select,
             "q4_naive": self.q4_naive,
             "q4_certificate_layout": self.q4_certificate_layout,
             "q4_joint_rank": self.q4_joint_rank,
             "cert_route_mode": self.cert_route_mode,
             "q4_residual_sparsify": self.q4_residual_sparsify,
             "q3_ml_ranker": self.q3_ml_ranker,
             "q3_ml_model_path": self.q3_ml_model_path,
             "active_scan_margin_m": self.active_scan_margin_m}
        if self.max_steps is not None:
            d["max_steps"] = self.max_steps
        return d

    def derive(self, **overrides):
        """派生 variant 配置（只改指定开关，其余继承）。"""
        d = self.to_dict()
        d.update(overrides)
        return MainlineConfig(**d)

    def __repr__(self):
        return "MainlineConfig(%s)" % self.to_dict()


# ---------------------------------------------------------------------------
# 读写
# ---------------------------------------------------------------------------

def _parse_yaml_subset(text):
    """无 pyyaml 时的迷你解析：仅支持 `key: value` 平铺（JSON 兼容子集）。"""
    out = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if ":" not in line:
            raise ConfigError("config line not 'key: value': %r" % line)
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if not key:
            raise ConfigError("empty config key in line %r" % line)
        try:
            out[key] = json.loads(val)
        except ValueError:
            out[key] = val  # 裸字符串（如 mainline / radius）
    return out


def load_config(path):
    """从 YAML/JSON 文件加载 MainlineConfig；path=None 返回默认配置。

    兼容 FROZEN_CONFIG.yaml：含 freeze_time 字段时只提取运行参数键。
    """
    if path is None:
        return MainlineConfig()
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if _HAS_YAML:
        data = yaml.safe_load(text) or {}
    else:  # pragma: no cover
        data = json.loads(text) if text.lstrip().startswith("{") \
            else _parse_yaml_subset(text)
    if not isinstance(data, dict):
        raise ConfigError("config root must be a mapping")
    if "freeze_time" in data:           # FROZEN_CONFIG.yaml
        data = {k: v for k, v in data.items() if k in _ALLOWED_KEYS}
    unknown = set(data) - _ALLOWED_KEYS
    if unknown:
        raise ConfigError("unknown config keys: %r (allowed: %r)"
                          % (sorted(unknown), sorted(_ALLOWED_KEYS)))
    return MainlineConfig(**data)


def config_sha256(path):
    """配置文件字节的 sha256（frozen_config_hash 用）；None → 默认配置哈希。"""
    if path is None:
        blob = json.dumps(MainlineConfig().to_dict(), sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def dump_config_yaml(config, path):
    """把有效配置写成 YAML 快照（run 目录 config.yaml）。"""
    data = config.to_dict()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if _HAS_YAML:
        text = "# effective config snapshot (Addendum E)\n" \
            + yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    else:  # pragma: no cover
        text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def git_commit(cwd=None):
    """当前 git HEAD；非 git 仓库返回 'N/A'（Addendum E.1 允许）。"""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=10, check=True)
        return out.stdout.decode("ascii").strip() or "N/A"
    except Exception:
        return "N/A"
