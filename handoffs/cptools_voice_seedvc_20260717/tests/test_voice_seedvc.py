from pathlib import Path

from ai_voice.voice_seedvc import build_seedvc_command, check_seedvc_ready, seedvc_status_message


def test_build_seedvc_v2_command_uses_source_target_and_similarity(tmp_path):
    repo = tmp_path / "seed-vc"
    source = tmp_path / "source.wav"
    target = tmp_path / "target.wav"
    output = tmp_path / "out"

    command = build_seedvc_command(
        repo_path=repo,
        python_executable="python3",
        source_wav_path=source,
        target_wav_path=target,
        output_dir=output,
        model_version="v2",
        diffusion_steps=30,
        length_adjust=1.0,
        similarity_cfg_rate=0.85,
        intelligibility_cfg_rate=0.7,
        convert_style=False,
    )

    assert command[:2] == ["python3", str(repo / "inference_v2.py")]
    assert command[command.index("--source") + 1] == str(source)
    assert command[command.index("--target") + 1] == str(target)
    assert command[command.index("--similarity-cfg-rate") + 1] == "0.85"


def test_seedvc_status_reports_missing_runtime(tmp_path):
    status = check_seedvc_ready(tmp_path / "missing-seed-vc", python_executable="python-that-does-not-exist")

    assert status["ready_for_cli"] is False
    assert "Seed-VC environment is not ready" in seedvc_status_message(status)
