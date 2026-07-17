import base64
import json

from ai_voice.voice_volcengine import VolcengineCredentials, load_volcengine_credentials, synthesize_seedicl2


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def iter_lines(self):
        yield json.dumps({"code": 0, "data": base64.b64encode(b"audio").decode()}).encode()
        yield json.dumps({"code": 20000000, "message": "OK"}).encode()


def test_load_credentials_normalizes_console_resource_name(tmp_path):
    env_file = tmp_path / "voice.env"
    env_file.write_text(
        "VOLCENGINE_APP_ID=app\n"
        "VOLCENGINE_ACCESS_TOKEN=token\n"
        "VOLCENGINE_RESOURCE_ID=TTS-SeedICL2.0\n",
        encoding="utf-8",
    )

    credentials = load_volcengine_credentials(env_file)

    assert credentials.resource_id == "seed-icl-2.0"


def test_synthesize_writes_streamed_audio(monkeypatch, tmp_path):
    captured = {}

    def fake_post(url, headers, json, stream, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "stream": stream, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("ai_voice.voice_volcengine.requests.post", fake_post)
    output = tmp_path / "out.mp3"
    result = synthesize_seedicl2(
        "测试台词",
        "speaker01",
        output,
        VolcengineCredentials("app", "token"),
        pitch_rate=-6,
    )

    assert output.read_bytes() == b"audio"
    assert result["code"] == 20000000
    assert captured["headers"]["X-Api-Resource-Id"] == "seed-icl-2.0"
    assert captured["json"]["req_params"]["audio_params"]["pitch_rate"] == -6
