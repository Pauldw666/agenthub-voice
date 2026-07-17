"""Seed-VC external adapter for CPtools Voice."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SEEDVC_REPO = Path("/Volumes/AI_training/AI项目落地验证/voice_models/seed-vc")


@dataclass(frozen=True)
class SeedVCResult:
    output_wav_path: str
    command: list[str]
    stdout: str
    stderr: str


def seedvc_repo_path(path: Path | str | None = None) -> Path:
    raw = path or os.environ.get("CPTOOLS_SEEDVC_REPO") or DEFAULT_SEEDVC_REPO
    return Path(raw).expanduser().resolve()


def check_seedvc_ready(repo_path: Path | str | None = None, python_executable: str | None = None) -> dict[str, object]:
    repo = seedvc_repo_path(repo_path)
    python_bin = python_executable or os.environ.get("CPTOOLS_SEEDVC_PYTHON") or "python3"
    inference_v1 = repo / "inference.py"
    inference_v2 = repo / "inference_v2.py"
    requirements_mac = repo / "requirements-mac.txt"
    checks = {
        "repo_path": str(repo),
        "repo_exists": repo.is_dir(),
        "inference_py": str(inference_v1),
        "inference_py_exists": inference_v1.is_file(),
        "inference_v2_py": str(inference_v2),
        "inference_v2_py_exists": inference_v2.is_file(),
        "requirements_mac": str(requirements_mac),
        "requirements_mac_exists": requirements_mac.is_file(),
        "python": python_bin,
        "python_found": shutil.which(python_bin) is not None,
        "torch_available": False,
        "torchaudio_available": False,
    }
    if checks["python_found"]:
        checks.update(python_import_checks(python_bin))
    checks["ready_for_cli"] = bool(
        checks["repo_exists"]
        and checks["inference_py_exists"]
        and checks["inference_v2_py_exists"]
        and checks["python_found"]
        and checks["torch_available"]
        and checks["torchaudio_available"]
    )
    return checks


def python_import_checks(python_bin: str) -> dict[str, bool]:
    script = (
        "import importlib.util;"
        "print('torch=' + str(importlib.util.find_spec('torch') is not None));"
        "print('torchaudio=' + str(importlib.util.find_spec('torchaudio') is not None))"
    )
    try:
        completed = subprocess.run(
            [python_bin, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return {"torch_available": False, "torchaudio_available": False}
    values: dict[str, bool] = {}
    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[f"{key.strip()}_available"] = value.strip() == "True"
    return {
        "torch_available": values.get("torch_available", False),
        "torchaudio_available": values.get("torchaudio_available", False),
    }


def convert_with_seedvc(
    source_wav_path: Path | str,
    target_wav_path: Path | str,
    output_dir: Path | str,
    *,
    repo_path: Path | str | None = None,
    python_executable: str | None = None,
    model_version: str = "v2",
    diffusion_steps: int = 30,
    length_adjust: float = 1.0,
    similarity_cfg_rate: float = 0.85,
    intelligibility_cfg_rate: float = 0.7,
    convert_style: bool = False,
    timeout: int = 900,
) -> SeedVCResult:
    repo = seedvc_repo_path(repo_path)
    python_bin = python_executable or os.environ.get("CPTOOLS_SEEDVC_PYTHON") or "python3"
    source_wav_path = Path(source_wav_path).expanduser().resolve()
    target_wav_path = Path(target_wav_path).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    status = check_seedvc_ready(repo, python_bin)
    if not status["ready_for_cli"]:
        raise RuntimeError(seedvc_status_message(status))

    before = time.time()
    command = build_seedvc_command(
        repo_path=repo,
        python_executable=python_bin,
        source_wav_path=source_wav_path,
        target_wav_path=target_wav_path,
        output_dir=output_dir,
        model_version=model_version,
        diffusion_steps=diffusion_steps,
        length_adjust=length_adjust,
        similarity_cfg_rate=similarity_cfg_rate,
        intelligibility_cfg_rate=intelligibility_cfg_rate,
        convert_style=convert_style,
    )
    completed = subprocess.run(
        command,
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    wavs = [
        path
        for path in output_dir.glob("*.wav")
        if path.is_file() and path.stat().st_mtime >= before - 1
    ]
    if not wavs:
        raise RuntimeError("Seed-VC finished but no wav output was found")
    newest = max(wavs, key=lambda path: path.stat().st_mtime)
    return SeedVCResult(
        output_wav_path=str(newest),
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def build_seedvc_command(
    *,
    repo_path: Path,
    python_executable: str,
    source_wav_path: Path,
    target_wav_path: Path,
    output_dir: Path,
    model_version: str,
    diffusion_steps: int,
    length_adjust: float,
    similarity_cfg_rate: float,
    intelligibility_cfg_rate: float,
    convert_style: bool,
) -> list[str]:
    if model_version == "v1":
        return [
            python_executable,
            str(repo_path / "inference.py"),
            "--source",
            str(source_wav_path),
            "--target",
            str(target_wav_path),
            "--output",
            str(output_dir),
            "--diffusion-steps",
            str(diffusion_steps),
            "--length-adjust",
            str(length_adjust),
            "--inference-cfg-rate",
            str(similarity_cfg_rate),
            "--f0-condition",
            "False",
            "--auto-f0-adjust",
            "False",
            "--fp16",
            "False",
        ]
    return [
        python_executable,
        str(repo_path / "inference_v2.py"),
        "--source",
        str(source_wav_path),
        "--target",
        str(target_wav_path),
        "--output",
        str(output_dir),
        "--diffusion-steps",
        str(diffusion_steps),
        "--length-adjust",
        str(length_adjust),
        "--intelligibility-cfg-rate",
        str(intelligibility_cfg_rate),
        "--similarity-cfg-rate",
        str(similarity_cfg_rate),
        "--convert-style",
        "true" if convert_style else "false",
    ]


def seedvc_status_message(status: dict[str, object]) -> str:
    missing: list[str] = []
    if not status.get("repo_exists"):
        missing.append("Seed-VC repo")
    if not status.get("inference_py_exists") or not status.get("inference_v2_py_exists"):
        missing.append("Seed-VC inference scripts")
    if not status.get("python_found"):
        missing.append("Seed-VC python")
    if not status.get("torch_available"):
        missing.append("torch")
    if not status.get("torchaudio_available"):
        missing.append("torchaudio")
    detail = ", ".join(missing) if missing else "unknown dependency"
    return (
        "Seed-VC environment is not ready: "
        f"{detail}. Repo: {status.get('repo_path')}; Python: {status.get('python')}"
    )
