"""Voice dubbing planning utilities.

The first version focuses on a provider-neutral workflow: read a script,
normalize lines into renderable segments, and write reviewable manifests.
Actual synthesis engines can then be plugged in without changing the
production-facing script format.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


FIELD_ALIASES = {
    "id": ["id", "ID", "编号", "序号", "镜头号", "条目"],
    "speaker": ["speaker", "role", "character", "voice", "voice_id", "说话人", "角色", "人物", "音色", "发音人"],
    "text": ["text", "line", "content", "script", "copy", "台词", "文本", "内容", "配音文本", "旁白"],
    "start": ["start", "start_time", "in", "tc_in", "record_in", "开始", "起始", "入点", "时间线入点"],
    "end": ["end", "end_time", "out", "tc_out", "record_out", "结束", "出点", "时间线出点"],
    "language": ["language", "lang", "语言"],
    "emotion": ["emotion", "mood", "style", "情绪", "风格"],
    "speed": ["speed", "rate", "tempo", "语速", "速度"],
    "volume": ["volume", "loudness", "音量"],
    "reference_audio": ["reference_audio", "ref_audio", "prompt_audio", "sample_audio", "参考音频", "样本音频", "提示音频"],
    "reference_text": ["reference_text", "ref_text", "prompt_text", "sample_text", "参考文本", "样本文本", "提示文本"],
    "instruction": ["instruction", "prompt", "directing", "指令", "导演提示", "口吻"],
    "notes": ["notes", "comment", "comments", "备注", "说明"],
}

SCRIPT_FIELDS = [
    "id",
    "speaker",
    "text",
    "start",
    "end",
    "language",
    "emotion",
    "speed",
    "volume",
    "reference_audio",
    "reference_text",
    "instruction",
    "notes",
    "source",
    "output_file",
]

SRT_TIMING_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
)
SPEAKER_PREFIX_RE = re.compile(r"^\s*(?:\[([^\]]{1,48})\]|([^:：\n]{1,48})[:：])\s*(.+?)\s*$")
MODEL_OPTIONS = [
    {
        "id": "cosyvoice3_local",
        "name": "Fun-CosyVoice3-0.5B-2512 local",
        "fit": "Best default for our own controllable tool",
        "strength": "Open model, zero-shot voice cloning, multilingual and dialect support, provider-neutral deployment.",
        "tradeoff": "Needs GPU deployment work and audio QA before production.",
    },
    {
        "id": "volcengine_doubao_tts",
        "name": "Volcengine / Doubao speech",
        "fit": "Good commercial API candidate if the Douyin enterprise account maps to API access",
        "strength": "Likely easiest path for China-based commercial stability and low-latency delivery.",
        "tradeoff": "Voice cloning and custom voice availability depend on account permissions and contract terms.",
    },
    {
        "id": "xfyun_tts_clone",
        "name": "iFlytek voice clone / TTS",
        "fit": "Good benchmark and backup commercial route",
        "strength": "Mature speech vendor, stable enterprise service path, useful for side-by-side quality tests.",
        "tradeoff": "Less transparent model control than our own CosyVoice deployment.",
    },
    {
        "id": "modelscope_cosyvoice3_api",
        "name": "ModelScope Fun-CosyVoice3 Studio API",
        "fit": "Useful temporary benchmark, not the long-term core",
        "strength": "Same public demo family as the old tool.",
        "tradeoff": "Requires ModelScope SDK token and has platform routing changes; not fully under our control.",
    },
]


@dataclass(frozen=True)
class VoiceSegment:
    id: str
    speaker: str
    text: str
    start: str = ""
    end: str = ""
    language: str = ""
    emotion: str = ""
    speed: str = ""
    volume: str = ""
    reference_audio: str = ""
    reference_text: str = ""
    instruction: str = ""
    notes: str = ""
    source: str = ""
    output_file: str = ""


@dataclass(frozen=True)
class VoicePlanResult:
    input_path: str
    output_dir: str
    provider: str
    plan_csv_path: str
    plan_json_path: str
    report_markdown_path: str
    summary: dict[str, Any]


def build_voice_plan(
    input_path: Path,
    output_dir: Path,
    provider: str = "cosyvoice3_local",
    project_name: str | None = None,
    default_speaker: str = "narrator",
    default_reference_audio: str = "",
    default_emotion: str = "",
    default_instruction: str = "",
    default_language: str = "",
) -> VoicePlanResult:
    input_path = input_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    segments = read_voice_script(input_path, default_speaker=default_speaker)
    if not segments:
        raise ValueError(f"No voice lines found in {input_path}")

    segments = [
        segment_with_defaults(
            segment,
            default_reference_audio=default_reference_audio,
            default_emotion=default_emotion,
            default_instruction=default_instruction,
            default_language=default_language,
        )
        for segment in segments
    ]
    project_slug = safe_slug(project_name or input_path.stem, fallback="voice_project")
    segments = [segment_with_output(segment, index, project_slug) for index, segment in enumerate(segments, start=1)]
    speaker_counts = Counter(segment.speaker for segment in segments)
    total_characters = sum(len(segment.text) for segment in segments)

    plan_csv_path = output_dir / f"{project_slug}_voice_plan.csv"
    plan_json_path = output_dir / f"{project_slug}_voice_plan.json"
    report_markdown_path = output_dir / f"{project_slug}_voice_report.md"

    write_plan_csv(plan_csv_path, segments)
    write_plan_json(
        plan_json_path,
        input_path=input_path,
        provider=provider,
        project_name=project_name or input_path.stem,
        segments=segments,
        speaker_counts=speaker_counts,
        total_characters=total_characters,
    )
    write_plan_markdown(
        report_markdown_path,
        input_path=input_path,
        provider=provider,
        project_name=project_name or input_path.stem,
        segments=segments,
        speaker_counts=speaker_counts,
        total_characters=total_characters,
    )

    return VoicePlanResult(
        input_path=str(input_path),
        output_dir=str(output_dir),
        provider=provider,
        plan_csv_path=str(plan_csv_path),
        plan_json_path=str(plan_json_path),
        report_markdown_path=str(report_markdown_path),
        summary={
            "segments": len(segments),
            "speakers": len(speaker_counts),
            "total_characters": total_characters,
            "missing_reference_audio": sum(1 for segment in segments if not segment.reference_audio),
        },
    )


def read_voice_script(path: Path, default_speaker: str = "narrator") -> list[VoiceSegment]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_voice_csv(path, default_speaker=default_speaker)
    if suffix == ".srt":
        return read_voice_srt(path, default_speaker=default_speaker)
    if suffix in {".txt", ".md"}:
        return read_voice_text(path, default_speaker=default_speaker)
    if suffix == ".json":
        return read_voice_json(path, default_speaker=default_speaker)
    raise ValueError(f"Unsupported voice script type: {path.suffix}")


def read_voice_csv(path: Path, default_speaker: str = "narrator") -> list[VoiceSegment]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    segments: list[VoiceSegment] = []
    for index, row in enumerate(rows, start=1):
        normalized = {normalize_header(key): value.strip() for key, value in row.items() if key and value is not None}
        text = pick_field(normalized, "text")
        if not text:
            continue
        raw_id = pick_field(normalized, "id") or f"V{index:04d}"
        speaker = clean_speaker(pick_field(normalized, "speaker") or default_speaker)
        segments.append(
            VoiceSegment(
                id=raw_id,
                speaker=speaker,
                text=text,
                start=pick_field(normalized, "start"),
                end=pick_field(normalized, "end"),
                language=pick_field(normalized, "language"),
                emotion=pick_field(normalized, "emotion"),
                speed=pick_field(normalized, "speed"),
                volume=pick_field(normalized, "volume"),
                reference_audio=pick_field(normalized, "reference_audio"),
                reference_text=pick_field(normalized, "reference_text"),
                instruction=pick_field(normalized, "instruction"),
                notes=pick_field(normalized, "notes"),
                source=f"{path.name}:row:{index}",
            )
        )
    return segments


def read_voice_srt(path: Path, default_speaker: str = "narrator") -> list[VoiceSegment]:
    text = path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", text.strip())
    segments: list[VoiceSegment] = []

    for block_index, block in enumerate(blocks, start=1):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        timing_index = next((idx for idx, line in enumerate(lines) if SRT_TIMING_RE.search(line)), -1)
        if timing_index == -1:
            continue

        match = SRT_TIMING_RE.search(lines[timing_index])
        assert match is not None
        body = " ".join(lines[timing_index + 1 :]).strip()
        if not body:
            continue

        speaker, clean_text = split_speaker_prefix(body, default_speaker=default_speaker)
        sequence = lines[0] if timing_index > 0 and lines[0].isdigit() else str(block_index)
        segments.append(
            VoiceSegment(
                id=f"SRT{int(sequence):04d}" if sequence.isdigit() else f"SRT{block_index:04d}",
                speaker=speaker,
                text=clean_text,
                start=match.group("start").replace(",", "."),
                end=match.group("end").replace(",", "."),
                source=f"{path.name}:block:{block_index}",
            )
        )
    return segments


def read_voice_text(path: Path, default_speaker: str = "narrator") -> list[VoiceSegment]:
    segments: list[VoiceSegment] = []
    for index, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        speaker, text = split_speaker_prefix(line, default_speaker=default_speaker)
        segments.append(
            VoiceSegment(
                id=f"V{len(segments) + 1:04d}",
                speaker=speaker,
                text=text,
                source=f"{path.name}:line:{index}",
            )
        )
    return segments


def read_voice_json(path: Path, default_speaker: str = "narrator") -> list[VoiceSegment]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("segments") or payload.get("lines") or []
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValueError("Voice JSON must be a list or contain a 'segments' list")

    segments: list[VoiceSegment] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        normalized = {normalize_header(str(key)): str(value).strip() for key, value in row.items() if value is not None}
        text = pick_field(normalized, "text")
        if not text:
            continue
        segments.append(
            VoiceSegment(
                id=pick_field(normalized, "id") or f"V{index:04d}",
                speaker=clean_speaker(pick_field(normalized, "speaker") or default_speaker),
                text=text,
                start=pick_field(normalized, "start"),
                end=pick_field(normalized, "end"),
                language=pick_field(normalized, "language"),
                emotion=pick_field(normalized, "emotion"),
                speed=pick_field(normalized, "speed"),
                volume=pick_field(normalized, "volume"),
                reference_audio=pick_field(normalized, "reference_audio"),
                reference_text=pick_field(normalized, "reference_text"),
                instruction=pick_field(normalized, "instruction"),
                notes=pick_field(normalized, "notes"),
                source=f"{path.name}:item:{index}",
            )
        )
    return segments


def write_provider_config_template(output_path: Path, provider: str = "cosyvoice3_local") -> Path:
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template = provider_config_template(provider)
    output_path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def provider_config_template(provider: str) -> dict[str, Any]:
    templates: dict[str, dict[str, Any]] = {
        "cosyvoice3_local": {
            "provider": "cosyvoice3_local",
            "model": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
            "runtime": "local_gpu",
            "server_url": "http://127.0.0.1:50000",
            "mode": "zero_shot",
            "notes": "Use this after the local CosyVoice service is deployed.",
        },
        "modelscope_cosyvoice3_api": {
            "provider": "modelscope_cosyvoice3_api",
            "endpoint": "https://studio-funaudiollm-fun-cosyvoice3-0-5b.api-inference.modelscope.net",
            "token_env": "MODELSCOPE_SDK_TOKEN",
            "model": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
            "notes": "The old *.ms.show URL rejects direct SDK-token access.",
        },
        "volcengine_doubao_tts": {
            "provider": "volcengine_doubao_tts",
            "app_id_env": "VOLCENGINE_APP_ID",
            "access_token_env": "VOLCENGINE_ACCESS_TOKEN",
            "secret_key_env": "VOLCENGINE_SECRET_KEY",
            "resource_id": "seed-icl-2.0",
            "speaker_id": "",
            "pitch_rate": -6,
            "quality_threshold": 0.9,
            "notes": "Doubao SeedICL 2.0; pitch -6 is the current reference-calibrated default.",
        },
        "xfyun_tts_clone": {
            "provider": "xfyun_tts_clone",
            "app_id_env": "XFYUN_APP_ID",
            "api_key_env": "XFYUN_API_KEY",
            "api_secret_env": "XFYUN_API_SECRET",
            "voice_id": "",
            "notes": "Fill with iFlytek voice clone / TTS account credentials.",
        },
    }
    if provider not in templates:
        raise ValueError(f"Unknown voice provider: {provider}")
    return templates[provider]


def model_options() -> list[dict[str, str]]:
    return [dict(option) for option in MODEL_OPTIONS]


def split_speaker_prefix(line: str, default_speaker: str = "narrator") -> tuple[str, str]:
    match = SPEAKER_PREFIX_RE.match(line)
    if not match:
        return clean_speaker(default_speaker), line.strip()

    speaker = match.group(1) or match.group(2) or default_speaker
    text = match.group(3).strip()
    if not text:
        return clean_speaker(default_speaker), line.strip()
    return clean_speaker(speaker), text


def pick_field(row: dict[str, str], canonical: str) -> str:
    for alias in FIELD_ALIASES[canonical]:
        value = row.get(normalize_header(alias), "")
        if value:
            return value.strip()
    return ""


def normalize_header(value: str) -> str:
    return re.sub(r"[\s_\-()（）/]+", "", value).casefold()


def clean_speaker(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    return value or "narrator"


def segment_with_output(segment: VoiceSegment, index: int, project_slug: str) -> VoiceSegment:
    speaker_slug = safe_slug(segment.speaker, fallback="speaker")
    line_slug = safe_slug(segment.id, fallback=f"line_{index:04d}")
    output_file = f"audio/{project_slug}_{index:04d}_{speaker_slug}_{line_slug}.wav"
    return VoiceSegment(**{**asdict(segment), "output_file": output_file})


def segment_with_defaults(
    segment: VoiceSegment,
    default_reference_audio: str = "",
    default_emotion: str = "",
    default_instruction: str = "",
    default_language: str = "",
) -> VoiceSegment:
    values = asdict(segment)
    if default_reference_audio and not segment.reference_audio:
        values["reference_audio"] = default_reference_audio
    if default_emotion and not segment.emotion:
        values["emotion"] = default_emotion
    if default_instruction and not segment.instruction:
        values["instruction"] = default_instruction
    if default_language and not segment.language:
        values["language"] = default_language
    return VoiceSegment(**values)


def safe_slug(value: str, fallback: str = "item") -> str:
    ascii_slug = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    if ascii_slug:
        return ascii_slug[:64]
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{fallback}_{digest}"


def write_plan_csv(path: Path, segments: Iterable[VoiceSegment]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCRIPT_FIELDS)
        writer.writeheader()
        for segment in segments:
            writer.writerow({field: getattr(segment, field) for field in SCRIPT_FIELDS})


def write_plan_json(
    path: Path,
    input_path: Path,
    provider: str,
    project_name: str,
    segments: list[VoiceSegment],
    speaker_counts: Counter[str],
    total_characters: int,
) -> None:
    payload = {
        "schema": "cptools.voice.plan.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project_name": project_name,
        "input_path": str(input_path),
        "provider": provider,
        "summary": {
            "segments": len(segments),
            "speakers": dict(sorted(speaker_counts.items())),
            "total_characters": total_characters,
            "missing_reference_audio": sum(1 for segment in segments if not segment.reference_audio),
        },
        "segments": [asdict(segment) for segment in segments],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_plan_markdown(
    path: Path,
    input_path: Path,
    provider: str,
    project_name: str,
    segments: list[VoiceSegment],
    speaker_counts: Counter[str],
    total_characters: int,
) -> None:
    missing_ref = sum(1 for segment in segments if not segment.reference_audio)
    lines = [
        "# CPtools Voice Plan",
        "",
        f"- Project: {project_name}",
        f"- Input: {input_path}",
        f"- Provider: {provider}",
        f"- Segments: {len(segments)}",
        f"- Speakers: {len(speaker_counts)}",
        f"- Characters: {total_characters}",
        f"- Missing reference audio: {missing_ref}",
        "",
        "## Speakers",
        "",
    ]
    for speaker, count in sorted(speaker_counts.items()):
        lines.append(f"- {speaker}: {count}")
    lines.extend(["", "## First Lines", ""])
    for segment in segments[:10]:
        preview = segment.text.replace("\n", " ")[:80]
        lines.append(f"- {segment.id} | {segment.speaker} | {preview}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
