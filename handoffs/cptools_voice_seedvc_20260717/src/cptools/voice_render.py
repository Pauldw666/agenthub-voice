"""Voice rendering adapters for CPtools Voice."""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .voice_seedvc import convert_with_seedvc
from .voice_quality import analyze_voice_similarity
from .voice_volcengine import load_volcengine_credentials, synthesize_seedicl2


@dataclass(frozen=True)
class RenderedVoiceSegment:
    id: str
    speaker: str
    text: str
    status: str
    output_wav_path: str
    output_mp3_path: str
    duration_seconds: float | None
    engine: str
    voice: str
    error: str = ""
    quality_status: str = ""
    quality_score: float | None = None
    quality_report_path: str = ""
    quality_artifact_risk: float | None = None
    quality_flags: tuple[str, ...] = ()
    quality_attempts: int = 0
    selected_pitch_rate: int | None = None
    selected_speech_rate: int | None = None
    selected_candidate_path: str = ""
    selected_text_variant: str = ""
    selected_render_text: str = ""
    source_audio_path: str = ""
    source_pitch_shift_semitones: float | None = None
    vc_model: str = ""
    vc_similarity: float | None = None


@dataclass(frozen=True)
class VoiceRenderResult:
    plan_json_path: str
    output_dir: str
    manifest_csv_path: str
    manifest_json_path: str
    summary: dict[str, Any]
    segments: list[RenderedVoiceSegment]


def render_voice_plan(
    plan_json_path: Path | str,
    engine: str = "system_say",
    voice: str = "Tingting",
    rate: int = 175,
    mp3: bool = True,
    overwrite: bool = True,
    credentials_file: Path | str | None = None,
    quality_reference_path: Path | str | None = None,
    quality_threshold: float = 0.9,
    pitch_rate: int = -6,
    speech_rate: int = 0,
    max_self_check_attempts: int = 12,
    strict_quality_gate: bool = True,
    seedvc_repo_path: Path | str | None = None,
    seedvc_python: str | None = None,
    seedvc_model: str = "v2",
    seedvc_source_voice: str = "Tingting",
    seedvc_diffusion_steps: int = 30,
    seedvc_similarity: float = 0.85,
    seedvc_intelligibility: float = 0.7,
    seedvc_convert_style: bool = False,
    seedvc_pitch_shifts: tuple[float, ...] = (0.0, -2.0, -4.0, 2.0),
) -> VoiceRenderResult:
    plan_json_path = Path(plan_json_path).expanduser().resolve()
    payload = json.loads(plan_json_path.read_text(encoding="utf-8"))
    output_dir = plan_json_path.parent
    segments = payload.get("segments", [])
    if not isinstance(segments, list) or not segments:
        raise ValueError("Voice plan has no segments to render")

    if engine not in {"system_say", "volcengine_clone", "seedvc_conversion"}:
        raise ValueError(f"Unsupported render engine for this build: {engine}")
    if engine == "system_say" and shutil.which("say") is None:
        raise RuntimeError("macOS say command is required for system_say rendering")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to convert rendered audio")

    credentials = None
    if engine == "volcengine_clone":
        credentials = load_volcengine_credentials(credentials_file)

    rendered: list[RenderedVoiceSegment] = []
    current_pitch_rate = pitch_rate
    current_speech_rate = speech_rate
    for segment in segments:
        if engine == "system_say":
            item = render_system_say_segment(
                segment=segment,
                output_dir=output_dir,
                voice=voice,
                rate=rate,
                mp3=mp3,
                overwrite=overwrite,
            )
        elif engine == "volcengine_clone":
            item = render_volcengine_segment(
                segment=segment,
                output_dir=output_dir,
                speaker_id=voice,
                credentials=credentials,
                mp3=mp3,
                overwrite=overwrite,
                quality_reference_path=quality_reference_path,
                quality_threshold=quality_threshold,
                pitch_rate=current_pitch_rate,
                speech_rate=current_speech_rate,
                max_self_check_attempts=max_self_check_attempts,
                strict_quality_gate=strict_quality_gate,
            )
            if (
                item.quality_status == "pass"
                and item.quality_score is not None
                and item.quality_score >= max(quality_threshold + 0.04, 0.94)
                and item.selected_pitch_rate is not None
                and item.selected_speech_rate is not None
            ):
                current_pitch_rate = item.selected_pitch_rate
                current_speech_rate = item.selected_speech_rate
        else:
            item = render_seedvc_segment(
                segment=segment,
                output_dir=output_dir,
                target_reference_path=quality_reference_path,
                mp3=mp3,
                overwrite=overwrite,
                quality_threshold=quality_threshold,
                strict_quality_gate=strict_quality_gate,
                repo_path=seedvc_repo_path,
                python_executable=seedvc_python,
                model_version=seedvc_model,
                source_voice=seedvc_source_voice,
                source_rate=rate,
                diffusion_steps=seedvc_diffusion_steps,
                similarity_cfg_rate=seedvc_similarity,
                intelligibility_cfg_rate=seedvc_intelligibility,
                convert_style=seedvc_convert_style,
                pitch_shifts=seedvc_pitch_shifts,
            )
        rendered.append(item)

    manifest_csv_path = output_dir / "render_manifest.csv"
    manifest_json_path = output_dir / "render_manifest.json"
    write_render_manifest_csv(manifest_csv_path, rendered)
    write_render_manifest_json(
        manifest_json_path,
        plan_json_path=plan_json_path,
        output_dir=output_dir,
        engine=engine,
        voice=voice,
        rate=rate,
        rendered=rendered,
    )
    summary = {
        "segments": len(rendered),
        "rendered": sum(1 for item in rendered if item.status == "rendered"),
        "skipped": sum(1 for item in rendered if item.status == "skipped"),
        "failed": sum(1 for item in rendered if item.status == "failed"),
        "held_for_review": sum(1 for item in rendered if item.status == "held_for_review"),
        "quality_passed": sum(1 for item in rendered if item.quality_status == "pass"),
        "quality_review": sum(1 for item in rendered if item.quality_status == "review"),
        "engine": engine,
        "voice": voice,
        "rate": rate,
    }
    return VoiceRenderResult(
        plan_json_path=str(plan_json_path),
        output_dir=str(output_dir),
        manifest_csv_path=str(manifest_csv_path),
        manifest_json_path=str(manifest_json_path),
        summary=summary,
        segments=rendered,
    )


def render_volcengine_segment(
    segment: dict[str, Any],
    output_dir: Path,
    speaker_id: str,
    credentials: Any,
    mp3: bool,
    overwrite: bool,
    quality_reference_path: Path | str | None,
    quality_threshold: float,
    pitch_rate: int,
    speech_rate: int,
    max_self_check_attempts: int,
    strict_quality_gate: bool,
) -> RenderedVoiceSegment:
    segment_id = str(segment.get("id") or "")
    speaker = str(segment.get("speaker") or "")
    text = str(segment.get("text") or "").strip()
    output_file = str(segment.get("output_file") or f"audio/{segment_id or 'line'}.wav")
    output_wav_path = (output_dir / output_file).resolve()
    output_mp3_path = output_wav_path.with_suffix(".mp3")
    output_wav_path.parent.mkdir(parents=True, exist_ok=True)

    if output_wav_path.exists() and not overwrite:
        return RenderedVoiceSegment(
            id=segment_id,
            speaker=speaker,
            text=text,
            status="skipped",
            output_wav_path=str(output_wav_path),
            output_mp3_path=str(output_mp3_path) if output_mp3_path.exists() else "",
            duration_seconds=probe_duration(output_wav_path),
            engine="volcengine_clone",
            voice=speaker_id,
        )

    try:
        reference = quality_reference_path or segment.get("reference_audio")
        if reference and Path(str(reference)).expanduser().is_file():
            best = render_self_checked_volcengine_candidate(
                text=text,
                speaker_id=speaker_id,
                output_dir=output_dir,
                segment_id=segment_id or "line",
                credentials=credentials,
                reference=Path(str(reference)),
                quality_threshold=quality_threshold,
                pitch_rate=pitch_rate,
                speech_rate=speech_rate,
                max_attempts=max_self_check_attempts,
            )
            if best["quality_status"] == "pass" or not strict_quality_gate:
                shutil.copy2(best["wav_path"], output_wav_path)
                if mp3:
                    shutil.copy2(best["mp3_path"], output_mp3_path)
                else:
                    output_mp3_path.unlink(missing_ok=True)
                status = "rendered" if best["quality_status"] == "pass" else "held_for_review"
            else:
                output_wav_path.unlink(missing_ok=True)
                output_mp3_path.unlink(missing_ok=True)
                status = "held_for_review"
            return RenderedVoiceSegment(
                id=segment_id,
                speaker=speaker,
                text=text,
                status=status,
                output_wav_path=str(output_wav_path),
                output_mp3_path=str(output_mp3_path) if output_mp3_path.exists() else "",
                duration_seconds=probe_duration(output_wav_path) if output_wav_path.exists() else None,
                engine="volcengine_clone",
                voice=speaker_id,
                error="" if status == "rendered" else "self_check_held_candidate",
                quality_status=str(best["quality_status"]),
                quality_score=float(best["quality_score"]),
                quality_report_path=str(best["quality_report_path"]),
                quality_artifact_risk=float(best["quality_artifact_risk"]),
                quality_flags=tuple(best["quality_flags"]),
                quality_attempts=int(best["quality_attempts"]),
                selected_pitch_rate=int(best["pitch_rate"]),
                selected_speech_rate=int(best["speech_rate"]),
                selected_candidate_path=str(best["wav_path"]),
                selected_text_variant=str(best.get("text_variant") or "original"),
                selected_render_text=str(best.get("render_text") or text),
            )

        synthesize_seedicl2(
            text=text,
            speaker_id=speaker_id,
            output_mp3_path=output_mp3_path,
            credentials=credentials,
            pitch_rate=pitch_rate,
            speech_rate=speech_rate,
        )
        convert_mp3_to_wav(output_mp3_path, output_wav_path)
        if not mp3:
            output_mp3_path.unlink(missing_ok=True)
        return RenderedVoiceSegment(
            id=segment_id,
            speaker=speaker,
            text=text,
            status="rendered",
            output_wav_path=str(output_wav_path),
            output_mp3_path=str(output_mp3_path) if output_mp3_path.exists() else "",
            duration_seconds=probe_duration(output_wav_path),
            engine="volcengine_clone",
            voice=speaker_id,
            quality_status="unchecked",
            quality_attempts=1,
            selected_pitch_rate=pitch_rate,
            selected_speech_rate=speech_rate,
        )
    except Exception as exc:  # noqa: BLE001 - preserve partial batch and report per-line failure.
        return RenderedVoiceSegment(
            id=segment_id,
            speaker=speaker,
            text=text,
            status="failed",
            output_wav_path=str(output_wav_path),
            output_mp3_path=str(output_mp3_path),
            duration_seconds=None,
            engine="volcengine_clone",
            voice=speaker_id,
            error=str(exc),
        )


def render_self_checked_volcengine_candidate(
    *,
    text: str,
    speaker_id: str,
    output_dir: Path,
    segment_id: str,
    credentials: Any,
    reference: Path,
    quality_threshold: float,
    pitch_rate: int,
    speech_rate: int,
    max_attempts: int,
) -> dict[str, Any]:
    candidate_dir = output_dir / "candidates" / segment_id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    best: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] = []
    for attempt_index, attempt_spec in enumerate(
        build_self_check_attempt_specs(text, pitch_rate, speech_rate, max_attempts),
        start=1,
    ):
        attempt_pitch = int(attempt_spec["pitch_rate"])
        attempt_speech = int(attempt_spec["speech_rate"])
        attempt_text = str(attempt_spec["text"])
        candidate_mp3 = candidate_dir / (
            f"attempt_{attempt_index:02d}_pitch_{attempt_pitch}_speed_{attempt_speech}.mp3"
        )
        candidate_wav = candidate_mp3.with_suffix(".wav")
        synthesize_seedicl2(
            text=attempt_text,
            speaker_id=speaker_id,
            output_mp3_path=candidate_mp3,
            credentials=credentials,
            pitch_rate=attempt_pitch,
            speech_rate=attempt_speech,
        )
        convert_mp3_to_wav(candidate_mp3, candidate_wav)
        candidate_quality = analyze_voice_similarity(
            reference,
            candidate_wav,
            candidate_dir / f"quality_attempt_{attempt_index:02d}",
            min_score=quality_threshold,
        )
        summary = candidate_quality.summary
        attempt = {
            "attempt": attempt_index,
            "pitch_rate": attempt_pitch,
            "speech_rate": attempt_speech,
            "mp3_path": str(candidate_mp3),
            "wav_path": str(candidate_wav),
            "quality_status": candidate_quality.status,
            "quality_score": float(summary["overall_proxy_score"]),
            "quality_artifact_risk": float(summary["ai_artifact_risk_score"]),
            "quality_flags": list(summary.get("risk_flags", [])),
            "quality_report_path": candidate_quality.report_json_path,
            "text_variant": attempt_spec["text_variant"],
            "render_text": attempt_text,
        }
        attempts.append(attempt)
        if best is None or candidate_rank(attempt) > candidate_rank(best):
            best = attempt
        if (
            attempt["quality_status"] == "pass"
            and attempt["quality_score"] >= max(quality_threshold + 0.03, 0.93)
            and attempt["quality_artifact_risk"] <= 0.22
        ):
            break

    if best is None:
        raise RuntimeError("Volcengine self-check produced no candidate")

    review_path = candidate_dir / "self_check_summary.json"
    review_payload = {
        "schema": "cptools.voice.self_check.v1",
        "segment_id": segment_id,
        "reference_path": str(reference),
        "selected_attempt": best["attempt"],
        "strict_release_rule": "Only pass candidates are copied into final audio output.",
        "attempts": attempts,
    }
    review_path.write_text(json.dumps(review_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    selected = dict(best)
    selected["quality_attempts"] = len(attempts)
    selected["self_check_summary_path"] = str(review_path)
    selected["mp3_path"] = Path(str(best["mp3_path"]))
    selected["wav_path"] = Path(str(best["wav_path"]))
    return selected


def build_self_check_settings(pitch_rate: int, speech_rate: int, max_attempts: int) -> list[tuple[int, int]]:
    offsets = [
        (0, 0),
        (2, 0),
        (-2, 0),
        (0, -2),
        (2, -2),
        (-4, 0),
        (-2, -2),
        (4, 0),
        (0, 2),
        (2, 2),
        (-6, 0),
        (-4, -2),
        (-2, 2),
        (4, -2),
    ]
    settings: list[tuple[int, int]] = []
    for pitch_offset, speech_offset in offsets:
        item = (clamp(pitch_rate + pitch_offset, -12, 12), clamp(speech_rate + speech_offset, -50, 100))
        if item not in settings:
            settings.append(item)
        if len(settings) >= max(1, max_attempts):
            break
    return settings


def build_self_check_attempt_specs(
    text: str,
    pitch_rate: int,
    speech_rate: int,
    max_attempts: int,
) -> list[dict[str, Any]]:
    parameter_settings = build_self_check_settings(pitch_rate, speech_rate, min(max(max_attempts, 1), 8))
    variants = build_text_self_check_variants(text)
    specs: list[dict[str, Any]] = []
    for attempt_pitch, attempt_speech in parameter_settings:
        specs.append(
            {
                "pitch_rate": attempt_pitch,
                "speech_rate": attempt_speech,
                "text": text,
                "text_variant": "original",
            }
        )
        if len(specs) >= max_attempts:
            return specs
    for variant_name, variant_text in variants[1:]:
        for attempt_pitch, attempt_speech in parameter_settings[:4]:
            specs.append(
                {
                    "pitch_rate": attempt_pitch,
                    "speech_rate": attempt_speech,
                    "text": variant_text,
                    "text_variant": variant_name,
                }
            )
            if len(specs) >= max_attempts:
                return specs
    return specs


def build_text_self_check_variants(text: str) -> list[tuple[str, str]]:
    variants: list[tuple[str, str]] = [("original", text)]
    if len(text) >= 16 and "，" in text:
        variants.append(("first_comma_as_sentence", text.replace("，", "。", 1)))
    with_clause_pause = re.sub(r"(一件一件地?|一点一点地?)", r"\1，", text)
    if with_clause_pause != text:
        variants.append(("clause_pause", with_clause_pause))
    if len(text) >= 22:
        midpoint = len(text) // 2
        if "，" not in text[max(0, midpoint - 3) : midpoint + 4]:
            variants.append(("mid_pause", f"{text[:midpoint]}，{text[midpoint:]}"))

    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, variant in variants:
        cleaned = normalize_tts_punctuation(variant)
        if cleaned and cleaned not in seen:
            unique.append((name, cleaned))
            seen.add(cleaned)
    return unique


def normalize_tts_punctuation(text: str) -> str:
    text = re.sub(r"，{2,}", "，", text)
    text = re.sub(r"。{2,}", "。", text)
    text = text.replace("，。", "。").replace("。，", "。")
    return text.strip()


def candidate_rank(candidate: dict[str, Any]) -> tuple[int, float, float]:
    pass_bonus = 1 if candidate["quality_status"] == "pass" else 0
    score = float(candidate["quality_score"])
    risk = float(candidate["quality_artifact_risk"])
    return (pass_bonus, score - 0.22 * risk, -risk)


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def convert_mp3_to_wav(src: Path, dst: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-ar",
            "24000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(dst),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def render_seedvc_segment(
    *,
    segment: dict[str, Any],
    output_dir: Path,
    target_reference_path: Path | str | None,
    mp3: bool,
    overwrite: bool,
    quality_threshold: float,
    strict_quality_gate: bool,
    repo_path: Path | str | None,
    python_executable: str | None,
    model_version: str,
    source_voice: str,
    source_rate: int,
    diffusion_steps: int,
    similarity_cfg_rate: float,
    intelligibility_cfg_rate: float,
    convert_style: bool,
    pitch_shifts: tuple[float, ...],
) -> RenderedVoiceSegment:
    segment_id = str(segment.get("id") or "")
    speaker = str(segment.get("speaker") or "")
    text = str(segment.get("text") or "").strip()
    output_file = str(segment.get("output_file") or f"audio/{segment_id or 'line'}.wav")
    output_wav_path = (output_dir / output_file).resolve()
    output_mp3_path = output_wav_path.with_suffix(".mp3")
    output_wav_path.parent.mkdir(parents=True, exist_ok=True)

    if output_wav_path.exists() and not overwrite:
        return RenderedVoiceSegment(
            id=segment_id,
            speaker=speaker,
            text=text,
            status="skipped",
            output_wav_path=str(output_wav_path),
            output_mp3_path=str(output_mp3_path) if output_mp3_path.exists() else "",
            duration_seconds=probe_duration(output_wav_path),
            engine="seedvc_conversion",
            voice=speaker,
        )

    reference = target_reference_path or segment.get("reference_audio")
    if not reference or not Path(str(reference)).expanduser().is_file():
        return RenderedVoiceSegment(
            id=segment_id,
            speaker=speaker,
            text=text,
            status="failed",
            output_wav_path=str(output_wav_path),
            output_mp3_path=str(output_mp3_path),
            duration_seconds=None,
            engine="seedvc_conversion",
            voice=speaker,
            error="Seed-VC requires a target reference audio file",
        )

    try:
        work_dir = output_dir / "seedvc" / (segment_id or "line")
        work_dir.mkdir(parents=True, exist_ok=True)
        source_wav = work_dir / "source_performance.wav"
        source_audio = segment.get("source_audio") or segment.get("performance_audio")
        if source_audio and Path(str(source_audio)).expanduser().is_file():
            normalize_audio_to_wav(Path(str(source_audio)), source_wav)
        else:
            synthesize_source_performance(text, source_wav, voice=source_voice, rate=source_rate)

        converted_dir = work_dir / "converted"
        best: dict[str, Any] | None = None
        attempts: list[dict[str, Any]] = []
        for attempt_index, shift in enumerate(unique_pitch_shifts(pitch_shifts), start=1):
            attempt_source = source_wav
            if shift:
                attempt_source = work_dir / f"source_pitch_{format_pitch_shift(shift)}.wav"
                pitch_shift_wav(source_wav, attempt_source, shift)
            attempt_dir = converted_dir / f"pitch_{format_pitch_shift(shift)}"
            result = convert_with_seedvc(
                attempt_source,
                reference,
                attempt_dir,
                repo_path=repo_path,
                python_executable=python_executable,
                model_version=model_version,
                diffusion_steps=diffusion_steps,
                similarity_cfg_rate=similarity_cfg_rate,
                intelligibility_cfg_rate=intelligibility_cfg_rate,
                convert_style=convert_style,
            )
            candidate_wav = work_dir / f"candidate_pitch_{format_pitch_shift(shift)}.wav"
            normalize_audio_to_wav(Path(result.output_wav_path), candidate_wav)
            quality = analyze_voice_similarity(
                reference,
                candidate_wav,
                work_dir / "quality" / f"pitch_{format_pitch_shift(shift)}",
                min_score=quality_threshold,
            )
            summary = quality.summary
            attempt = {
                "attempt": attempt_index,
                "source_pitch_shift_semitones": shift,
                "source_audio_path": str(attempt_source),
                "candidate_wav_path": str(candidate_wav),
                "quality_status": quality.status,
                "quality_score": float(summary["overall_proxy_score"]),
                "quality_artifact_risk": float(summary["ai_artifact_risk_score"]),
                "quality_flags": list(summary.get("risk_flags", [])),
                "quality_report_path": quality.report_json_path,
            }
            attempts.append(attempt)
            if best is None or candidate_rank(attempt) > candidate_rank(best):
                best = attempt
            if (
                attempt["quality_status"] == "pass"
                and attempt["quality_score"] >= max(quality_threshold + 0.03, 0.93)
                and attempt["quality_artifact_risk"] <= 0.22
            ):
                break

        if best is None:
            raise RuntimeError("Seed-VC self-check produced no candidate")

        review_path = work_dir / "self_check_summary.json"
        review_payload = {
            "schema": "cptools.voice.seedvc.self_check.v1",
            "segment_id": segment_id or "line",
            "reference_path": str(reference),
            "selected_attempt": best["attempt"],
            "strict_release_rule": "Only pass candidates are copied into final audio output.",
            "attempts": attempts,
        }
        review_path.write_text(json.dumps(review_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        candidate_wav = Path(str(best["candidate_wav_path"]))
        quality_status = str(best["quality_status"])
        quality_score = float(best["quality_score"])
        quality_artifact_risk = float(best["quality_artifact_risk"])
        quality_flags = tuple(best["quality_flags"])
        if quality_status == "pass" or not strict_quality_gate:
            shutil.copy2(candidate_wav, output_wav_path)
            if mp3:
                encode_wav_to_mp3(output_wav_path, output_mp3_path)
            else:
                output_mp3_path.unlink(missing_ok=True)
            status = "rendered" if quality_status == "pass" else "held_for_review"
        else:
            output_wav_path.unlink(missing_ok=True)
            output_mp3_path.unlink(missing_ok=True)
            status = "held_for_review"

        return RenderedVoiceSegment(
            id=segment_id,
            speaker=speaker,
            text=text,
            status=status,
            output_wav_path=str(output_wav_path),
            output_mp3_path=str(output_mp3_path) if output_mp3_path.exists() else "",
            duration_seconds=probe_duration(output_wav_path) if output_wav_path.exists() else None,
            engine="seedvc_conversion",
            voice=speaker,
            error="" if status == "rendered" else "seedvc_self_check_held_candidate",
            quality_status=quality_status,
            quality_score=quality_score,
            quality_report_path=str(best["quality_report_path"]),
            quality_artifact_risk=quality_artifact_risk,
            quality_flags=quality_flags,
            quality_attempts=len(attempts),
            selected_candidate_path=str(candidate_wav),
            selected_text_variant="source_performance",
            selected_render_text=text,
            source_audio_path=str(best["source_audio_path"]),
            source_pitch_shift_semitones=float(best["source_pitch_shift_semitones"]),
            vc_model=model_version,
            vc_similarity=similarity_cfg_rate,
        )
    except Exception as exc:  # noqa: BLE001 - keep batch-level progress visible.
        return RenderedVoiceSegment(
            id=segment_id,
            speaker=speaker,
            text=text,
            status="failed",
            output_wav_path=str(output_wav_path),
            output_mp3_path=str(output_mp3_path),
            duration_seconds=None,
            engine="seedvc_conversion",
            voice=speaker,
            error=str(exc),
        )


def synthesize_source_performance(text: str, output_wav_path: Path, voice: str, rate: int) -> None:
    if shutil.which("say") is None:
        raise RuntimeError("macOS say command is required to create a source performance automatically")
    with tempfile.TemporaryDirectory(prefix="cptools_seedvc_source_") as tmp:
        aiff_path = Path(tmp) / "source.aiff"
        subprocess.run(
            ["say", "-v", voice, "-r", str(rate), "-o", str(aiff_path), text],
            check=True,
            capture_output=True,
            text=True,
        )
        normalize_audio_to_wav(aiff_path, output_wav_path)


def normalize_audio_to_wav(src: Path, dst: Path, sample_rate: int = 24000) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(dst),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def unique_pitch_shifts(values: tuple[float, ...]) -> list[float]:
    shifts: list[float] = []
    for value in values or (0.0,):
        shift = round(float(value), 3)
        if shift not in shifts:
            shifts.append(shift)
    return shifts or [0.0]


def format_pitch_shift(value: float) -> str:
    rounded = round(float(value), 3)
    prefix = "m" if rounded < 0 else "p"
    body = f"{abs(rounded):g}".replace(".", "p")
    return f"{prefix}{body}"


def pitch_shift_wav(src: Path, dst: Path, semitones: float, sample_rate: int = 24000) -> None:
    factor = 2 ** (float(semitones) / 12)
    atempo = 1 / factor
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-af",
            f"asetrate={round(sample_rate * factor)},aresample={sample_rate},atempo={atempo:.6f}",
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(dst),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def encode_wav_to_mp3(src: Path, dst: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(dst),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def render_system_say_segment(
    segment: dict[str, Any],
    output_dir: Path,
    voice: str,
    rate: int,
    mp3: bool,
    overwrite: bool,
) -> RenderedVoiceSegment:
    segment_id = str(segment.get("id") or "")
    speaker = str(segment.get("speaker") or "")
    text = str(segment.get("text") or "").strip()
    output_file = str(segment.get("output_file") or f"audio/{segment_id or 'line'}.wav")
    output_wav_path = (output_dir / output_file).resolve()
    output_mp3_path = output_wav_path.with_suffix(".mp3")
    output_wav_path.parent.mkdir(parents=True, exist_ok=True)

    if not text:
        return RenderedVoiceSegment(
            id=segment_id,
            speaker=speaker,
            text=text,
            status="failed",
            output_wav_path=str(output_wav_path),
            output_mp3_path=str(output_mp3_path),
            duration_seconds=None,
            engine="system_say",
            voice=voice,
            error="empty_text",
        )

    if output_wav_path.exists() and not overwrite:
        return RenderedVoiceSegment(
            id=segment_id,
            speaker=speaker,
            text=text,
            status="skipped",
            output_wav_path=str(output_wav_path),
            output_mp3_path=str(output_mp3_path) if output_mp3_path.exists() else "",
            duration_seconds=probe_duration(output_wav_path),
            engine="system_say",
            voice=voice,
        )

    try:
        with tempfile.TemporaryDirectory(prefix="cptools_voice_") as tmp:
            aiff_path = Path(tmp) / "say.aiff"
            subprocess.run(
                ["say", "-v", voice, "-r", str(rate), "-o", str(aiff_path), text],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(aiff_path),
                    "-ar",
                    "48000",
                    "-ac",
                    "1",
                    "-af",
                    "loudnorm=I=-16:TP=-1.5:LRA=11",
                    str(output_wav_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            if mp3:
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-v",
                        "error",
                        "-i",
                        str(output_wav_path),
                        "-codec:a",
                        "libmp3lame",
                        "-b:a",
                        "192k",
                        str(output_mp3_path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
    except subprocess.CalledProcessError as exc:
        return RenderedVoiceSegment(
            id=segment_id,
            speaker=speaker,
            text=text,
            status="failed",
            output_wav_path=str(output_wav_path),
            output_mp3_path=str(output_mp3_path),
            duration_seconds=None,
            engine="system_say",
            voice=voice,
            error=(exc.stderr or exc.stdout or str(exc)).strip(),
        )

    return RenderedVoiceSegment(
        id=segment_id,
        speaker=speaker,
        text=text,
        status="rendered",
        output_wav_path=str(output_wav_path),
        output_mp3_path=str(output_mp3_path) if output_mp3_path.exists() else "",
        duration_seconds=probe_duration(output_wav_path),
        engine="system_say",
        voice=voice,
    )


def probe_duration(path: Path) -> float | None:
    if shutil.which("ffprobe") is None:
        return None
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return round(float(completed.stdout.strip()), 3)
    except (subprocess.SubprocessError, ValueError):
        return None


def write_render_manifest_csv(path: Path, rendered: list[RenderedVoiceSegment]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "speaker",
                "text",
                "status",
                "output_wav_path",
                "output_mp3_path",
                "duration_seconds",
                "engine",
                "voice",
                "error",
                "quality_status",
                "quality_score",
                "quality_report_path",
                "quality_artifact_risk",
                "quality_flags",
                "quality_attempts",
                "selected_pitch_rate",
                "selected_speech_rate",
                "selected_candidate_path",
                "selected_text_variant",
                "selected_render_text",
                "source_audio_path",
                "source_pitch_shift_semitones",
                "vc_model",
                "vc_similarity",
            ],
        )
        writer.writeheader()
        for item in rendered:
            writer.writerow(asdict(item))


def write_render_manifest_json(
    path: Path,
    plan_json_path: Path,
    output_dir: Path,
    engine: str,
    voice: str,
    rate: int,
    rendered: list[RenderedVoiceSegment],
) -> None:
    payload = {
        "schema": "cptools.voice.render.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "plan_json_path": str(plan_json_path),
        "output_dir": str(output_dir),
        "engine": engine,
        "voice": voice,
        "rate": rate,
        "summary": {
            "segments": len(rendered),
            "rendered": sum(1 for item in rendered if item.status == "rendered"),
            "skipped": sum(1 for item in rendered if item.status == "skipped"),
            "failed": sum(1 for item in rendered if item.status == "failed"),
            "held_for_review": sum(1 for item in rendered if item.status == "held_for_review"),
            "quality_passed": sum(1 for item in rendered if item.quality_status == "pass"),
            "quality_review": sum(1 for item in rendered if item.quality_status == "review"),
        },
        "segments": [asdict(item) for item in rendered],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
