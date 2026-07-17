from cptools.cli import main
from cptools.voice import build_voice_plan
from cptools.voice_quality import analyze_voice_similarity
from cptools.voice_volcengine import VolcengineCredentials


def test_cptools_voice_import_path_is_available(tmp_path, capsys):
    script = tmp_path / "script.txt"
    script.write_text("旁白：旧 App 仍然可以导入 cptools.voice。", encoding="utf-8")

    result = build_voice_plan(script, tmp_path / "out")

    assert result.summary["segments"] == 1
    assert callable(analyze_voice_similarity)
    assert VolcengineCredentials("app", "token").app_id == "app"

    exit_code = main(["voice", "models"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "cosyvoice3_local" in output

