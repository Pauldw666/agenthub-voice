import json
import shutil
import threading
from pathlib import Path
from urllib.parse import quote
import urllib.request
import wave

import pytest

from cptools.voice_app import (
    VoiceAppServer,
    create_reference_template,
    list_audio_references,
    preview_segments_with_outputs,
    probe_audio,
    resolve_allowed_path,
)


def write_tiny_wav(path):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)


def test_voice_app_lists_reference_audio(tmp_path):
    wav_path = tmp_path / "R1_03_闫妮参考.wav"
    write_tiny_wav(wav_path)

    references = list_audio_references(tmp_path)

    assert len(references) == 1
    assert references[0].name == "R1_03_闫妮参考.wav"
    assert references[0].extension == "wav"
    assert references[0].size_mb > 0


def test_voice_app_api_generates_plan_with_selected_reference(tmp_path):
    reference_dir = tmp_path / "refs"
    reference_dir.mkdir()
    wav_path = reference_dir / "R1_03_闫妮参考.wav"
    write_tiny_wav(wav_path)
    reference = list_audio_references(reference_dir)[0]

    server = VoiceAppServer(("127.0.0.1", 0), reference_dir=reference_dir, output_dir=tmp_path / "out")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/plan"
        body = json.dumps(
            {
                "project_name": "人工测试",
                "provider": "cosyvoice3_local",
                "speaker": "闫妮",
                "emotion": "自然",
                "instruction": "真实口语",
                "script_text": "这事儿吧，咱们慢慢说。",
                "reference_id": reference.id,
            }
        ).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        assert payload["ok"] is True
        assert payload["preview_segments"][0]["speaker"] == "闫妮"
        assert payload["preview_segments"][0]["reference_audio"] == str(wav_path)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_preview_segments_exposes_output_audio_when_file_exists(tmp_path):
    output_dir = tmp_path / "session"
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True)
    wav_path = audio_dir / "line_0001.wav"
    write_tiny_wav(wav_path)

    segments = preview_segments_with_outputs(
        [{"id": "V0001", "output_file": "audio/line_0001.wav"}],
        output_dir=output_dir,
    )

    assert segments[0]["output_exists"] is True
    assert segments[0]["output_audio_path"] == str(wav_path.resolve())
    assert segments[0]["output_audio_url"].startswith("/output-audio?path=")


def test_output_audio_endpoint_serves_allowed_generated_audio(tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    wav_path = output_dir / "rendered.wav"
    write_tiny_wav(wav_path)

    server = VoiceAppServer(("127.0.0.1", 0), reference_dir=tmp_path, output_dir=output_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/output-audio?path={quote(str(wav_path), safe='')}"
        with urllib.request.urlopen(url, timeout=5) as response:
            assert response.status == 200
            assert response.read(4) == b"RIFF"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_resolve_allowed_path_rejects_paths_outside_roots(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    inside = root / "plan.json"
    outside = tmp_path / "outside.json"
    inside.write_text("{}", encoding="utf-8")
    outside.write_text("{}", encoding="utf-8")

    assert resolve_allowed_path(str(inside), [root]) == inside.resolve()
    assert resolve_allowed_path(str(outside), [root]) is None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="reference template editor requires ffmpeg")
def test_create_reference_template_joins_audio_as_24k_mono(tmp_path):
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    output = tmp_path / "templates" / "joined.wav"
    write_tiny_wav(first)
    write_tiny_wav(second)

    create_reference_template([first, second], output, gap_seconds=0.15)

    metadata = probe_audio(output)
    assert output.is_file()
    assert metadata["sample_rate"] == 24000
    assert metadata["channels"] == 1
    assert metadata["duration_seconds"] >= 0.34
