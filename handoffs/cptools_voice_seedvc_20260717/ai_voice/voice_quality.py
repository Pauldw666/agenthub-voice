"""Audio quality checks for voice clone candidates."""

from __future__ import annotations

import json
import math
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class VoiceQualityResult:
    reference_path: str
    candidate_path: str
    report_json_path: str
    status: str
    summary: dict[str, Any]


def analyze_voice_similarity(
    reference_path: Path | str,
    candidate_path: Path | str,
    output_dir: Path | str,
    min_score: float = 0.9,
    max_ai_risk: float = 0.34,
) -> VoiceQualityResult:
    reference_path = Path(reference_path).expanduser().resolve()
    candidate_path = Path(candidate_path).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    reference_wav = output_dir / "quality_reference_16k.wav"
    candidate_wav = output_dir / "quality_candidate_16k.wav"
    convert_to_wav16(reference_path, reference_wav)
    convert_to_wav16(candidate_path, candidate_wav)

    reference = extract_audio_features(reference_wav)
    candidate = extract_audio_features(candidate_wav)
    scores = compare_audio_features(reference, candidate)
    status = (
        "pass"
        if scores["overall_proxy_score"] >= min_score
        and scores["ai_artifact_risk_score"] <= max_ai_risk
        and not scores["risk_flags"]
        else "review"
    )

    report = {
        "schema": "cptools.voice.quality.v1",
        "reference_path": str(reference_path),
        "candidate_path": str(candidate_path),
        "status": status,
        "threshold": min_score,
        "max_ai_risk": max_ai_risk,
        "summary": scores,
        "reference_features": without_embedding(reference),
        "candidate_features": without_embedding(candidate),
        "notes": [
            "This automatic reviewer combines timbre, pitch, brightness, rhythm, and energy-dynamics proxies.",
            "It is designed to block obvious AI-flavored or mismatched candidates before manual listening.",
        ],
    }
    report_json_path = output_dir / "quality_report.json"
    report_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return VoiceQualityResult(
        reference_path=str(reference_path),
        candidate_path=str(candidate_path),
        report_json_path=str(report_json_path),
        status=status,
        summary=scores,
    )


def convert_to_wav16(src: Path, dst: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-ar", "16000", "-ac", "1", str(dst)], check=True)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        sample_rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return audio, sample_rate


def extract_audio_features(path: Path) -> dict[str, Any]:
    audio, sample_rate = read_wav(path)
    if not len(audio):
        raise ValueError(f"Empty audio: {path}")
    audio = audio / (np.max(np.abs(audio)) + 1e-9) * 0.95
    frames = frame_signal(audio, sample_rate)
    window = np.hanning(frames.shape[1])
    pitches, rms = pitch_autocorr(frames, sample_rate)
    spec = np.abs(np.fft.rfft(frames * window, n=512)) ** 2
    freqs = np.fft.rfftfreq(512, 1 / sample_rate)
    energy = spec.sum(axis=1) + 1e-12
    centroid = (spec * freqs).sum(axis=1) / energy
    cumsum = np.cumsum(spec, axis=1)
    rolloff = freqs[np.argmax(cumsum >= 0.85 * energy[:, None], axis=1)]
    zcr = np.mean(np.abs(np.diff(np.sign(frames), axis=1)), axis=1) / 2
    mel = np.log(np.maximum(spec @ mel_filterbank(sample_rate).T, 1e-9))
    voiced = rms > max(0.01, np.percentile(rms, 35))
    mel_use = mel[voiced] if np.any(voiced) else mel
    rms_use = rms[voiced] if np.any(voiced) else rms
    rms_db_frames = 20 * np.log10(rms_use + 1e-9)
    embedding = np.concatenate([mel_use.mean(axis=0), mel_use.std(axis=0)])
    return {
        "duration": round(len(audio) / sample_rate, 3),
        "rms_db": round(20 * np.log10(float(np.sqrt(np.mean(audio * audio))) + 1e-9), 2),
        "pitch_median": round(float(np.median(pitches)), 2) if len(pitches) else None,
        "pitch_iqr": round(float(np.percentile(pitches, 75) - np.percentile(pitches, 25)), 2) if len(pitches) else None,
        "pitch_count": int(len(pitches)),
        "voiced_ratio": round(float(len(pitches) / max(len(frames), 1)), 4),
        "rms_iqr_db": round(float(np.percentile(rms_db_frames, 75) - np.percentile(rms_db_frames, 25)), 2),
        "rms_std_db": round(float(np.std(rms_db_frames)), 2),
        "centroid_median": round(float(np.median(centroid)), 2),
        "rolloff_median": round(float(np.median(rolloff)), 2),
        "zcr_median": round(float(np.median(zcr)), 4),
        "embedding": embedding,
    }


def frame_signal(audio: np.ndarray, sample_rate: int, frame_ms: int = 40, hop_ms: int = 10) -> np.ndarray:
    frame = int(sample_rate * frame_ms / 1000)
    hop = int(sample_rate * hop_ms / 1000)
    if len(audio) < frame:
        audio = np.pad(audio, (0, frame - len(audio)))
    frame_count = 1 + (len(audio) - frame) // hop
    return np.stack([audio[index * hop : index * hop + frame] for index in range(max(frame_count, 1))])


def pitch_autocorr(frames: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    pitches: list[float] = []
    rms_values: list[float] = []
    for frame in frames:
        frame = frame - np.mean(frame)
        rms = float(np.sqrt(np.mean(frame * frame) + 1e-12))
        rms_values.append(rms)
        if rms < 0.01:
            continue
        corr = np.correlate(frame, frame, mode="full")[len(frame) - 1 :]
        min_lag = int(sample_rate / 450)
        max_lag = min(int(sample_rate / 70), len(corr) - 1)
        candidates = corr[min_lag:max_lag]
        if not len(candidates):
            continue
        lag = int(np.argmax(candidates) + min_lag)
        confidence = corr[lag] / (corr[0] + 1e-9)
        pitch = sample_rate / lag if lag else 0
        if confidence > 0.28 and 70 <= pitch <= 450:
            pitches.append(float(pitch))
    return np.array(pitches), np.array(rms_values)


def mel_filterbank(sample_rate: int, n_fft: int = 512, n_mels: int = 32, fmin: int = 80, fmax: int = 7600) -> np.ndarray:
    def hz_to_mel(hz: float) -> float:
        return 2595 * np.log10(1 + hz / 700)

    def mel_to_hz(mel: float) -> float:
        return 700 * (10 ** (mel / 2595) - 1)

    mels = np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2)
    bins = np.floor((n_fft + 1) * np.array([mel_to_hz(mel) for mel in mels]) / sample_rate).astype(int)
    filters = np.zeros((n_mels, n_fft // 2 + 1))
    for index in range(1, n_mels + 1):
        left, center, right = bins[index - 1], bins[index], bins[index + 1]
        if center > left:
            filters[index - 1, left:center] = (np.arange(left, center) - left) / (center - left)
        if right > center:
            filters[index - 1, center:right] = (right - np.arange(center, right)) / (right - center)
    return filters


def compare_audio_features(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    timbre_similarity = (cosine(reference["embedding"], candidate["embedding"]) + 1) / 2
    pitch_score = 0.0
    if reference["pitch_median"] and candidate["pitch_median"]:
        ratio = abs(math.log(candidate["pitch_median"] / reference["pitch_median"]))
        pitch_score = max(0.0, 1 - ratio / 0.45)
    centroid_score = max(0.0, 1 - abs(candidate["centroid_median"] - reference["centroid_median"]) / 2200)
    zcr_score = max(0.0, 1 - abs(candidate["zcr_median"] - reference["zcr_median"]) / 0.10)
    prosody_score = log_ratio_score(reference.get("pitch_iqr"), candidate.get("pitch_iqr"), tolerance=0.95)
    energy_dynamics_score = log_ratio_score(
        reference.get("rms_iqr_db"),
        candidate.get("rms_iqr_db"),
        tolerance=1.15,
        floor=0.15,
    )
    voiced_score = max(0.0, 1 - abs(candidate["voiced_ratio"] - reference["voiced_ratio"]) / 0.45)
    overall = (
        0.42 * timbre_similarity
        + 0.22 * pitch_score
        + 0.12 * centroid_score
        + 0.07 * zcr_score
        + 0.10 * prosody_score
        + 0.05 * energy_dynamics_score
        + 0.02 * voiced_score
    )

    risk_flags = build_review_flags(
        timbre_similarity=timbre_similarity,
        pitch_score=pitch_score,
        centroid_score=centroid_score,
        prosody_score=prosody_score,
        energy_dynamics_score=energy_dynamics_score,
        reference=reference,
        candidate=candidate,
    )
    hard_review_flags = [
        flag
        for flag in risk_flags
        if flag in {"timbre_mismatch", "pitch_drift", "over_bright_or_over_dark"}
    ]
    ai_artifact_risk = (
        0.33 * (1 - timbre_similarity)
        + 0.22 * (1 - pitch_score)
        + 0.16 * (1 - prosody_score)
        + 0.13 * (1 - energy_dynamics_score)
        + 0.10 * (1 - centroid_score)
        + 0.04 * (1 - zcr_score)
        + 0.02 * (1 - voiced_score)
    )
    return {
        "timbre_logmel_similarity": round(float(timbre_similarity), 4),
        "pitch_score": round(float(pitch_score), 4),
        "centroid_score": round(float(centroid_score), 4),
        "zcr_score": round(float(zcr_score), 4),
        "prosody_variation_score": round(float(prosody_score), 4),
        "energy_dynamics_score": round(float(energy_dynamics_score), 4),
        "voiced_ratio_score": round(float(voiced_score), 4),
        "overall_proxy_score": round(float(overall), 4),
        "ai_artifact_risk_score": round(float(ai_artifact_risk), 4),
        "risk_flags": risk_flags,
        "hard_review_flags": hard_review_flags,
    }


def log_ratio_score(
    reference_value: float | int | None,
    candidate_value: float | int | None,
    tolerance: float,
    floor: float = 0.05,
) -> float:
    if reference_value is None or candidate_value is None:
        return 0.65
    reference_float = max(float(reference_value), floor)
    candidate_float = max(float(candidate_value), floor)
    ratio = abs(math.log(candidate_float / reference_float))
    return max(0.0, 1 - ratio / tolerance)


def build_review_flags(
    *,
    timbre_similarity: float,
    pitch_score: float,
    centroid_score: float,
    prosody_score: float,
    energy_dynamics_score: float,
    reference: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    if timbre_similarity < 0.86:
        flags.append("timbre_mismatch")
    if pitch_score < 0.82:
        flags.append("pitch_drift")
    if centroid_score < 0.72:
        flags.append("over_bright_or_over_dark")
    if prosody_score < 0.62:
        flags.append("prosody_too_flat_or_unstable")
    if energy_dynamics_score < 0.58:
        flags.append("energy_too_flat_or_pumped")
    if reference.get("pitch_iqr") and candidate.get("pitch_iqr") and float(reference["pitch_iqr"]) >= 12.0:
        if float(candidate["pitch_iqr"]) < float(reference["pitch_iqr"]) * 0.45:
            flags.append("pitch_variation_too_flat")
    if reference.get("rms_iqr_db") and candidate.get("rms_iqr_db") and float(reference["rms_iqr_db"]) >= 2.0:
        if float(candidate["rms_iqr_db"]) < float(reference["rms_iqr_db"]) * 0.45:
            flags.append("energy_variation_too_flat")
    return flags


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right) + 1e-9))


def without_embedding(features: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in features.items() if key != "embedding"}
