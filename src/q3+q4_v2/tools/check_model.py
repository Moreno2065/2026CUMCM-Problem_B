"""Contract entry point for the t9 verify command.

The t9 contract names ``tools/check_model.py``; the actual model/ledger
self-check lives in ``verification/check_model.py`` and remains the single
source of truth.  This file only forwards to it in-process, so the contracted
command runs verbatim without duplicating any check logic and without touching
the exit code (``runpy.run_path`` executes the target as ``__main__``, so its
``sys.exit(main())`` propagates unchanged).

Future verify lines should name ``verification/check_model.py`` directly.
"""
from __future__ import annotations

import runpy
from pathlib import Path

TARGET = (Path(__file__).resolve().parents[1] / "verification" /
          "check_model.py")

if __name__ == "__main__":
    runpy.run_path(str(TARGET), run_name="__main__")
