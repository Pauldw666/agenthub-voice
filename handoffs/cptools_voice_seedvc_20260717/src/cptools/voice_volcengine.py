"""Volcengine/Doubao SeedICL 2.0 voice synthesis client."""

from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import requests


DEFAULT_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DEFAULT_RESOURCE_ID = "seed-icl-2.0"
DEFAULT_MODEL = "seed-tts-2.0-standard"


@dataclass(frozen=True)
class VolcengineCredentials:
    app_id: str
    access_token: str
    secret_key: str = ""
    resource_id: str = DEFAULT_RESOURCE_ID


def load_env_file(path: Path | str) -> dict[str, str]:
    path = Path(path).expanduser().resolve()
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def load_volcengine_credentials(env_file: Path | str | None = None) -> VolcengineCredentials:
    values = dict(os.environ)
    if env_file is not None:
        values.update(load_env_file(env_file))
    app_id = values.get("VOLCENGINE_APP_ID", "").strip()
    access_token = values.get("VOLCENGINE_ACCESS_TOKEN", "").strip()
    if not app_id or not access_token:
        raise RuntimeError("Volcengine credentials are missing: configure VOLCENGINE_APP_ID and VOLCENGINE_ACCESS_TOKEN")
    resource_id = values.get("VOLCENGINE_RESOURCE_ID", DEFAULT_RESOURCE_ID).strip().lower()
    if resource_id == "tts-seedicl2.0":
        resource_id = DEFAULT_RESOURCE_ID
    return VolcengineCredentials(
        app_id=app_id,
        access_token=access_token,
        secret_key=values.get("VOLCENGINE_SECRET_KEY", "").strip(),
        resource_id=resource_id or DEFAULT_RESOURCE_ID,
    )


def synthesize_seedicl2(
    text: str,
    speaker_id: str,
    output_mp3_path: Path | str,
    credentials: VolcengineCredentials,
    pitch_rate: int = -6,
    speech_rate: int = 0,
    sample_rate: int = 24000,
    timeout: int = 180,
) -> dict[str, object]:
    text = text.strip()
    speaker_id = speaker_id.strip()
    if not text:
        raise ValueError("TTS text is empty")
    if not speaker_id:
        raise ValueError("Volcengine speaker_id is empty")

    headers = {
        "Content-Type": "application/json",
        "X-Api-App-Id": credentials.app_id,
        "X-Api-Access-Key": credentials.access_token,
        "X-Api-Resource-Id": credentials.resource_id,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Control-Require-Usage-Tokens-Return": "*",
    }
    payload = {
        "req_params": {
            "text": text,
            "speaker": speaker_id,
            "model": DEFAULT_MODEL,
            "audio_params": {
                "format": "mp3",
                "sample_rate": sample_rate,
                "bit_rate": 128000,
                "pitch_rate": pitch_rate,
                "speech_rate": speech_rate,
            },
        }
    }

    response = requests.post(DEFAULT_ENDPOINT, headers=headers, json=payload, stream=True, timeout=timeout)
    response.raise_for_status()
    audio = bytearray()
    final_code: int | None = None
    final_message = ""
    usage: dict[str, object] = {}
    for line in response.iter_lines():
        if not line:
            continue
        item = json.loads(line)
        final_code = item.get("code")
        final_message = str(item.get("message") or "")
        if item.get("data"):
            audio.extend(base64.b64decode(item["data"]))
        if isinstance(item.get("usage"), dict):
            usage.update(item["usage"])

    if not audio:
        raise RuntimeError(f"Volcengine returned no audio: code={final_code}, message={final_message}")
    if final_code not in (0, 20000000):
        raise RuntimeError(f"Volcengine synthesis failed: code={final_code}, message={final_message}")

    output_mp3_path = Path(output_mp3_path).expanduser().resolve()
    output_mp3_path.parent.mkdir(parents=True, exist_ok=True)
    output_mp3_path.write_bytes(audio)
    return {
        "code": final_code,
        "message": final_message,
        "audio_bytes": len(audio),
        "usage": usage,
        "pitch_rate": pitch_rate,
        "speech_rate": speech_rate,
        "speaker_id": speaker_id,
    }
