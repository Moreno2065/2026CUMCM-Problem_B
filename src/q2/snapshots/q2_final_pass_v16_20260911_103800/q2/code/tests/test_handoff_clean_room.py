"""End-to-end clean-room verification for the exported Q2 handoff ZIP.

Run with ``Q2_HANDOFF_ZIP`` pointing at the archive.  The test deliberately
launches child pytest processes with a temporary extraction root as their sole
``PYTHONPATH`` so the original workspace cannot satisfy imports.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest


def test_handoff_clean_room(tmp_path: Path) -> None:
    archive_value = os.environ.get("Q2_HANDOFF_ZIP")
    if not archive_value:
        pytest.skip("set Q2_HANDOFF_ZIP to run the clean-room handoff audit")
    archive = Path(archive_value).resolve()
    if not archive.is_file():
        raise AssertionError(f"handoff archive is missing: {archive}")

    copied_archive = tmp_path / "Q2_FINAL_HANDOFF.zip"
    shutil.copy2(archive, copied_archive)
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with zipfile.ZipFile(copied_archive) as bundle:
        bundle.extractall(extracted)
    root = extracted / "Q2_FINAL_HANDOFF"
    if not (root / "src/q1/code/q1_geometry.py").is_file():
        raise AssertionError("clean-room package does not contain the Q1 runtime")
    if not (root / "src/q2/code/solver/gate_g.py").is_file():
        raise AssertionError("clean-room package does not contain the Q2 runtime")

    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(root)
    environment.pop("Q2_HANDOFF_ZIP", None)
    commands = [
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "src/q1/code/tests"],
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "src/q2/code/tests/test_gate_a.py",
            "src/q2/code/tests/test_gate_b.py",
            "src/q2/code/tests/test_gate_c.py",
            "src/q2/code/tests/test_gate_d.py",
            "src/q2/code/tests/test_gate_e.py",
            "src/q2/code/tests/test_gate_f.py",
            "src/q2/code/tests/test_gate_g.py",
            "src/q2/code/tests/test_gate_g_prime.py",
            "src/q2/code/tests/test_final_package.py",
        ],
    ]
    outputs: list[str] = []
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        output = completed.stdout + completed.stderr
        outputs.append(output)
        assert completed.returncode == 0, output
        assert str(Path("D:/CUMCM2026")) not in output

    (tmp_path / "clean_room_test_output.txt").write_text(
        "\n--- Q1 ---\n" + outputs[0] + "\n--- Q2 ---\n" + outputs[1],
        encoding="utf-8",
    )
