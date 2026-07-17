import shutil
import wave
import json

import pytest

from ai_voice.voice_quality import analyze_voice_similarity


def write_tone(path, frequency=220, seconds=0.5, sample_rate=16000):
    import math

    frames = []
    for index in range(int(seconds * sample_rate)):
        value = int(math.sin(2 * math.pi * frequency * index / sample_rate) * 12000)
        frames.append(value.to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"".join(frames))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="quality check requires ffmpeg")
def test_quality_check_passes_for_identical_audio(tmp_path):
    audio = tmp_path / "tone.wav"
    write_tone(audio)

    result = analyze_voice_similarity(audio, audio, tmp_path / "quality", min_score=0.95)

    assert result.status == "pass"
    assert result.summary["overall_proxy_score"] >= 0.95
    assert result.summary["ai_artifact_risk_score"] <= 0.05
    assert result.report_json_path.endswith("quality_report.json")
    report = json.loads(open(result.report_json_path, encoding="utf-8").read())
    assert report["max_ai_risk"] == 0.34


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="quality check requires ffmpeg")
def test_quality_check_marks_pitch_drift_for_mismatched_audio(tmp_path):
    reference = tmp_path / "reference.wav"
    candidate = tmp_path / "candidate.wav"
    write_tone(reference, frequency=220)
    write_tone(candidate, frequency=390)

    result = analyze_voice_similarity(reference, candidate, tmp_path / "quality", min_score=0.9)

    assert result.status == "review"
    assert "pitch_drift" in result.summary["risk_flags"]
