import csv
import json
from pathlib import Path

from cptools.cli import main
from cptools.voice import build_voice_plan, provider_config_template, read_voice_script


def test_read_text_script_splits_speakers(tmp_path):
    script = tmp_path / "ad.txt"
    script.write_text(
        "\n".join(
            [
                "旁白：今天我们把声音也纳入 CPtools。",
                "[客户] 这条要更可信一点。",
                "没有角色前缀时走默认说话人。",
            ]
        ),
        encoding="utf-8",
    )

    segments = read_voice_script(script, default_speaker="默认")

    assert [segment.speaker for segment in segments] == ["旁白", "客户", "默认"]
    assert segments[0].text == "今天我们把声音也纳入 CPtools。"
    assert segments[1].text == "这条要更可信一点。"


def test_read_srt_keeps_timing_and_role_prefix(tmp_path):
    srt = tmp_path / "lines.srt"
    srt.write_text(
        "\n".join(
            [
                "1",
                "00:00:01,000 --> 00:00:03,000",
                "旁白：先把台词变成可检查的任务。",
                "",
                "2",
                "00:00:04,000 --> 00:00:06,500",
                "客户：然后再交给模型渲染。",
            ]
        ),
        encoding="utf-8",
    )

    segments = read_voice_script(srt)

    assert segments[0].id == "SRT0001"
    assert segments[0].start == "00:00:01.000"
    assert segments[0].end == "00:00:03.000"
    assert segments[0].speaker == "旁白"
    assert segments[1].speaker == "客户"


def test_build_voice_plan_writes_review_files(tmp_path):
    script = tmp_path / "launch.csv"
    with script.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["编号", "说话人", "台词", "情绪", "参考音频"])
        writer.writeheader()
        writer.writerow({"编号": "A001", "说话人": "旁白", "台词": "第一条。", "情绪": "calm", "参考音频": "voice/narrator.wav"})
        writer.writerow({"编号": "A002", "说话人": "角色A", "台词": "第二条。", "情绪": "bright", "参考音频": ""})

    result = build_voice_plan(script, tmp_path / "out", project_name="品牌片")
    plan = json.loads(Path(result.plan_json_path).read_text(encoding="utf-8"))

    assert result.summary["segments"] == 2
    assert result.summary["speakers"] == 2
    assert result.summary["missing_reference_audio"] == 1
    assert plan["schema"] == "cptools.voice.plan.v1"
    assert plan["segments"][0]["output_file"].endswith(".wav")
    assert result.plan_csv_path.endswith("_voice_plan.csv")
    assert result.report_markdown_path.endswith("_voice_report.md")


def test_provider_template_documents_modelscope_endpoint_change():
    template = provider_config_template("modelscope_cosyvoice3_api")

    assert template["endpoint"].startswith("https://studio-funaudiollm")
    assert template["token_env"] == "MODELSCOPE_SDK_TOKEN"
    assert "*.ms.show" in template["notes"]


def test_voice_cli_plan_and_models(tmp_path, capsys):
    script = tmp_path / "voice.txt"
    script.write_text("narrator: One clean line.", encoding="utf-8")

    exit_code = main(["voice", "plan", str(script), "--output-dir", str(tmp_path / "reports")])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Segments: 1" in output
    assert "Plan JSON:" in output

    exit_code = main(["voice", "models"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "cosyvoice3_local" in output
    assert "xfyun_tts_clone" in output
