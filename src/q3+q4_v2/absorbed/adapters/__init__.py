# -*- coding: utf-8 -*-
"""absorbed.adapters —— v2 运行栈 ↔ Q3_Q4_V3 solver client 契约的适配层。

模块职责（每个模块都在 import 期只依赖标准库）：

- :mod:`v3_client`          把 v2 的 ``ActionExecutor`` 包装成源引擎期望的
                            client：``act('/measure'|'/clear'|'/enter'|'/exit')``
                            + ``position`` / ``channel`` / ``virtual`` / ``rows``。
- :mod:`runtime_bridge`     sys.path 准备、后端构造（官方 http /
                            http-synthetic / 进程内 synthetic）、v2
                            ``runtime.report_line`` 惰性复用、JSON 安全化、
                            参数指纹。
- :mod:`absorbed_verifier`  吸收运行结果的独立校验；能复用 v2 verifier 原语的
                            地方真复用（``verify_q3_cover`` /
                            ``verify_mec_covers``），不能复用的显式登记为
                            not_performed。
- :mod:`socket_guard`       vendored bridge 全局禁用 socket/urllib 的导入期
                            防护（身份快照 + import 前后各断言一次）。

导入期零副作用：本包在 import 期不构造客户端、不开 socket、不改 sys.path。
"""

from .socket_guard import (SocketBindingTampered, capture, check_pristine,
                           compare, describe, remediation)
from .runtime_bridge import (build_backend, build_metrics, ensure_v2_import_path,
                             json_safe, load_report_line, parameter_fingerprint,
                             shutdown_backend)
from .v3_client import AbsorbedActionRejected, AbsorbedSolverClient
from .absorbed_verifier import verify_absorbed_run

__all__ = [
    "SocketBindingTampered", "capture", "check_pristine", "compare",
    "describe", "remediation",
    "build_backend", "build_metrics", "ensure_v2_import_path", "json_safe",
    "load_report_line", "parameter_fingerprint", "shutdown_backend",
    "AbsorbedActionRejected", "AbsorbedSolverClient",
    "verify_absorbed_run",
]
