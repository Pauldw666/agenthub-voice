import json
import shutil

import pytest

from ai_voice.voice import build_voice_plan
from ai_voice.voice_render import (
    build_self_check_attempt_specs,
    build_self_check_settings,
    build_text_self_check_variants,
    format_pitch_shift,
    render_voice_plan,
    unique_pitch_shifts,
)


def test_build_self_check_settings_keeps_base_first_and_clamps():
    settings = build_self_check_settings(-11, 0, max_attempts=4)

    assert settings[0] == (-11, 0)
    assert len(settings) == 4
    assert all(-12 <= pitch <= 12 for pitch, _speech in settings)


def test_build_text_self_check_variants_adds_pause_without_changing_words():
    variants = build_text_self_check_variants("你先别着急，咱们把前因后果一件一件理清楚。")

    assert variants[0][0] == "original"
    assert any(name == "first_comma_as_sentence" for name, _text in variants)
    assert all("一件一件，地" not in text for _name, text in variants)


def test_build_self_check_attempt_specs_reserves_room_for_text_variants():
    specs = build_self_check_attempt_specs("你先别着急，咱们把前因后果一件一件理清楚。", -6, 0, 12)

    assert len(specs) == 12
    assert specs[0]["text_variant"] == "original"
    assert any(spec["text_variant"] != "original" for spec in specs)


def test_seedvc_pitch_shift_helpers_are_stable():
    assert unique_pitch_shifts((0, -2, -2, 1.5)) == [0.0, -2.0, 1.5]
    assert format_pitch_shift(0) == "p0"
    assert format_pitch_shift(-2) == "m2"
    assert format_pitch_shift(1.5) == "p1p5"


@pytest.mark.skipif(shutil.which("say") is None or shutil.which("ffmpeg") is None, reason="system_say renderer requires macOS say and ffmpeg")
def test_render_voice_plan_writes_wav_and_mp3(tmp_path):
    script = tmp_path / "script.txt"
    script.write_text("旁白：今天先出一条测试音频。", encoding="utf-8")
    plan = build_voice_plan(script, tmp_path / "out", project_name="render_test")

    result = render_voice_plan(plan.plan_json_path, voice="Tingting", rate=175)

    assert result.summary["rendered"] == 1
    assert result.summary["failed"] == 0
    rendered = result.segments[0]
    assert rendered.output_wav_path.endswith(".wav")
    assert rendered.output_mp3_path.endswith(".mp3")
    assert rendered.duration_seconds and rendered.duration_seconds > 0
    assert result.manifest_csv_path.endswith("render_manifest.csv")
    payload = json.loads(open(result.manifest_json_path, encoding="utf-8").read())
    assert payload["schema"] == "cptools.voice.render.v1"
