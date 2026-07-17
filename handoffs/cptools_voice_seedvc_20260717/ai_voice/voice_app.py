"""Local CPtools voice testing app."""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import subprocess
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.parse import unquote

from .voice import build_voice_plan, model_options, provider_config_template, write_provider_config_template
from .voice_render import render_voice_plan
from .voice_seedvc import DEFAULT_SEEDVC_REPO, check_seedvc_ready


AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg"}
DEFAULT_REFERENCE_DIR = Path("/Volumes/AI_training/AI配音软件/CANKAO")
DEFAULT_OUTPUT_DIR = Path("data/reports/voice_app")
DEFAULT_VOLCENGINE_CREDENTIALS = Path(".secrets/volcengine.env")


@dataclass(frozen=True)
class AudioReference:
    id: str
    name: str
    path: str
    relative_path: str
    extension: str
    size_mb: float
    duration_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    codec: str = ""
    bit_rate: int | None = None


def list_audio_references(reference_dir: Path, id_prefix: str = "source") -> list[AudioReference]:
    reference_dir = reference_dir.expanduser().resolve()
    if not reference_dir.exists():
        return []

    references: list[AudioReference] = []
    for path in sorted(reference_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        references.append(build_audio_reference(path, reference_dir, id_prefix=id_prefix))
    return references


def build_audio_reference(path: Path, reference_dir: Path, id_prefix: str = "source") -> AudioReference:
    metadata = probe_audio(path)
    relative_path = path.relative_to(reference_dir).as_posix()
    return AudioReference(
        id=reference_id(f"{id_prefix}:{relative_path}"),
        name=path.name,
        path=str(path),
        relative_path=relative_path,
        extension=path.suffix.lower().lstrip("."),
        size_mb=round(path.stat().st_size / 1000 / 1000, 3),
        duration_seconds=metadata.get("duration_seconds"),
        sample_rate=metadata.get("sample_rate"),
        channels=metadata.get("channels"),
        codec=metadata.get("codec", ""),
        bit_rate=metadata.get("bit_rate"),
    )


def probe_audio(path: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,bit_rate:stream=codec_name,sample_rate,channels",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {}

    stream = next((item for item in payload.get("streams", []) if "sample_rate" in item), {})
    fmt = payload.get("format", {})
    return {
        "duration_seconds": parse_float(fmt.get("duration")),
        "sample_rate": parse_int(stream.get("sample_rate")),
        "channels": parse_int(stream.get("channels")),
        "codec": str(stream.get("codec_name") or ""),
        "bit_rate": parse_int(fmt.get("bit_rate")),
    }


def reference_id(relative_path: str) -> str:
    import hashlib

    return hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:16]


def parse_float(value: Any) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def parse_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def preview_segments_with_outputs(segments: list[dict[str, Any]], output_dir: Path) -> list[dict[str, Any]]:
    output_dir = output_dir.expanduser().resolve()
    enriched: list[dict[str, Any]] = []
    for segment in segments:
        item = dict(segment)
        output_file = str(item.get("output_file") or "")
        output_path = (output_dir / output_file).resolve() if output_file else None
        if output_path is not None and is_path_allowed(output_path, [output_dir]):
            item["output_audio_path"] = str(output_path)
            item["output_exists"] = output_path.is_file()
            item["output_audio_url"] = (
                f"/output-audio?path={quote_path(str(output_path))}"
                if output_path.is_file() and output_path.suffix.lower() in AUDIO_EXTENSIONS
                else ""
            )
        else:
            item["output_audio_path"] = ""
            item["output_exists"] = False
            item["output_audio_url"] = ""
        enriched.append(item)
    return enriched


def latest_render_manifest(output_dir: Path) -> Path | None:
    output_dir = output_dir.expanduser().resolve()
    manifests = [path for path in output_dir.rglob("render_manifest.json") if path.is_file()]
    if not manifests:
        return None
    return max(manifests, key=lambda path: path.stat().st_mtime)


def render_manifest_segments_with_outputs(payload: dict[str, Any], allowed_root: Path) -> list[dict[str, Any]]:
    allowed_root = allowed_root.expanduser().resolve()
    enriched: list[dict[str, Any]] = []
    for segment in payload.get("segments", []):
        item = {
            "id": str(segment.get("id") or ""),
            "speaker": str(segment.get("speaker") or ""),
            "text": str(segment.get("text") or ""),
            "reference_audio": "",
            "output_file": str(segment.get("output_wav_path") or ""),
            "status": str(segment.get("status") or ""),
            "quality_status": str(segment.get("quality_status") or ""),
            "quality_score": segment.get("quality_score"),
            "quality_artifact_risk": segment.get("quality_artifact_risk"),
            "quality_flags": list(segment.get("quality_flags") or []),
            "quality_attempts": segment.get("quality_attempts"),
            "selected_pitch_rate": segment.get("selected_pitch_rate"),
            "selected_speech_rate": segment.get("selected_speech_rate"),
            "selected_candidate_path": str(segment.get("selected_candidate_path") or ""),
            "selected_text_variant": str(segment.get("selected_text_variant") or ""),
            "selected_render_text": str(segment.get("selected_render_text") or ""),
            "source_audio_path": str(segment.get("source_audio_path") or ""),
            "source_pitch_shift_semitones": segment.get("source_pitch_shift_semitones"),
            "vc_model": str(segment.get("vc_model") or ""),
            "vc_similarity": segment.get("vc_similarity"),
        }
        output_path = resolve_allowed_path(str(segment.get("output_wav_path") or ""), [allowed_root])
        if output_path is not None and output_path.is_file():
            item["output_audio_path"] = str(output_path)
            item["output_exists"] = True
            item["output_audio_url"] = f"/output-audio?path={quote_path(str(output_path))}"
        else:
            item["output_audio_path"] = ""
            item["output_exists"] = False
            item["output_audio_url"] = ""
        enriched.append(item)
    return enriched


def quote_path(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def resolve_allowed_path(raw_path: str, roots: list[Path]) -> Path | None:
    if not raw_path:
        return None
    try:
        path = Path(raw_path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    return path if is_path_allowed(path, roots) else None


def is_path_allowed(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.expanduser().resolve(strict=False)
        resolved_roots = [root.expanduser().resolve(strict=False) for root in roots]
        return any(os.path.commonpath([str(resolved), str(root)]) == str(root) for root in resolved_roots)
    except (OSError, RuntimeError, ValueError):
        return False


def open_local_path(path: Path, reveal: bool = False) -> None:
    if reveal and path.is_file():
        subprocess.run(["open", "-R", str(path)], check=False)
        return
    subprocess.run(["open", str(path)], check=False)


def create_reference_template(
    source_paths: list[Path],
    output_path: Path,
    gap_seconds: float = 0.15,
    max_duration: float = 29.8,
) -> Path:
    if len(source_paths) < 2:
        raise ValueError("请至少选择两条参考音频再拼接。")
    if not all(path.is_file() for path in source_paths):
        raise ValueError("有参考音频已不存在，请重新选择。")
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = ["ffmpeg", "-y", "-v", "error"]
    for path in source_paths:
        command.extend(["-i", str(path)])
    filters: list[str] = []
    concat_inputs: list[str] = []
    for index in range(len(source_paths)):
        filters.append(
            f"[{index}:a]aresample=24000,aformat=sample_fmts=s16:channel_layouts=mono[a{index}]"
        )
        concat_inputs.append(f"[a{index}]")
        if index < len(source_paths) - 1:
            filters.append(f"anullsrc=r=24000:cl=mono:d={gap_seconds}[g{index}]")
            concat_inputs.append(f"[g{index}]")
    filters.append(f"{''.join(concat_inputs)}concat=n={len(concat_inputs)}:v=0:a=1[out]")
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-t",
            str(max_duration),
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )
    subprocess.run(command, check=True, capture_output=True, text=True)
    return output_path


class VoiceAppServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], reference_dir: Path, output_dir: Path):
        super().__init__(server_address, VoiceAppHandler)
        self.reference_dir = reference_dir.expanduser().resolve()
        self.output_dir = output_dir.expanduser().resolve()
        self.generated_reference_dir = self.output_dir / "reference_templates"
        self.generated_reference_dir.mkdir(parents=True, exist_ok=True)
        self.started_at = time.time()

    def references(self) -> list[AudioReference]:
        return list_audio_references(self.reference_dir, id_prefix="source") + list_audio_references(
            self.generated_reference_dir, id_prefix="template"
        )


class VoiceAppHandler(BaseHTTPRequestHandler):
    server: VoiceAppServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_text(render_app_html(), content_type="text/html; charset=utf-8")
            return
        if parsed.path == "/api/references":
            self.send_json({"references": [asdict(item) for item in self.server.references()]})
            return
        if parsed.path == "/api/models":
            self.send_json({"models": model_options()})
            return
        if parsed.path == "/api/seedvc-status":
            self.send_json({"ok": True, "status": check_seedvc_ready()})
            return
        if parsed.path == "/api/latest-render":
            self.handle_latest_render()
            return
        if parsed.path == "/api/config-template":
            query = parse_qs(parsed.query)
            provider = query.get("provider", ["cosyvoice3_local"])[0]
            try:
                self.send_json(provider_config_template(provider))
            except ValueError as exc:
                self.send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/audio":
            self.stream_audio(parsed.query)
            return
        if parsed.path == "/output-audio":
            self.stream_output_audio(parsed.query)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/plan":
            self.handle_plan()
            return
        if parsed.path == "/api/config-template":
            self.handle_config_template()
            return
        if parsed.path == "/api/render":
            self.handle_render()
            return
        if parsed.path == "/api/reference-template":
            self.handle_reference_template()
            return
        if parsed.path == "/api/open-path":
            self.handle_open_path()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def handle_plan(self) -> None:
        try:
            payload = self.read_json()
            script_text = str(payload.get("script_text") or "").strip()
            if not script_text:
                self.send_error_json("请先填写要测试的台词。", HTTPStatus.BAD_REQUEST)
                return

            reference = self.find_reference(str(payload.get("reference_id") or ""))
            reference_path = reference.path if reference else ""
            project_name = str(payload.get("project_name") or "voice_test").strip() or "voice_test"
            session_dir = self.server.output_dir / time.strftime("%Y%m%d_%H%M%S")
            session_dir.mkdir(parents=True, exist_ok=True)
            script_path = session_dir / "script.txt"
            script_path.write_text(script_text + "\n", encoding="utf-8")

            result = build_voice_plan(
                input_path=script_path,
                output_dir=session_dir,
                provider=str(payload.get("provider") or "cosyvoice3_local"),
                project_name=project_name,
                default_speaker=str(payload.get("speaker") or "narrator"),
                default_reference_audio=reference_path,
                default_emotion=str(payload.get("emotion") or ""),
                default_instruction=str(payload.get("instruction") or ""),
                default_language=str(payload.get("language") or "zh"),
            )
            plan_payload = json.loads(Path(result.plan_json_path).read_text(encoding="utf-8"))
            self.send_json(
                {
                    "ok": True,
                    "message": "配音计划已生成。当前版本尚未接入渲染引擎，所以这里只生成计划和输出位置。",
                    "reference": asdict(reference) if reference else None,
                    "result": asdict(result),
                    "preview_segments": preview_segments_with_outputs(
                        plan_payload.get("segments", [])[:12],
                        output_dir=Path(result.output_dir),
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 - local app should report recoverable errors.
            self.send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_config_template(self) -> None:
        try:
            payload = self.read_json()
            provider = str(payload.get("provider") or "cosyvoice3_local")
            output_path = self.server.output_dir / "provider_config.json"
            config_path = write_provider_config_template(output_path, provider=provider)
            self.send_json({"ok": True, "path": str(config_path), "config": provider_config_template(provider)})
        except Exception as exc:  # noqa: BLE001
            self.send_error_json(str(exc), HTTPStatus.BAD_REQUEST)

    def handle_latest_render(self) -> None:
        manifest_path = latest_render_manifest(self.server.output_dir)
        if manifest_path is None:
            self.send_error_json("还没有找到已渲染批次。", HTTPStatus.NOT_FOUND)
            return
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        output_dir = Path(str(payload.get("output_dir") or manifest_path.parent))
        self.send_json(
            {
                "ok": True,
                "message": f"已加载最近成品批次：{payload.get('summary', {}).get('rendered', 0)} 条音频。",
                "result": {
                    "output_dir": str(output_dir),
                    "manifest_json_path": str(manifest_path),
                    "manifest_csv_path": str(manifest_path.with_suffix(".csv")),
                },
                "preview_segments": render_manifest_segments_with_outputs(payload, allowed_root=self.server.output_dir),
            }
        )

    def handle_render(self) -> None:
        try:
            payload = self.read_json()
            plan_path = resolve_allowed_path(str(payload.get("plan_json_path") or ""), [self.server.output_dir])
            if plan_path is None or not plan_path.is_file():
                self.send_error_json("请先生成配音计划，再渲染音频。", HTTPStatus.BAD_REQUEST)
                return
            result = render_voice_plan(
                plan_json_path=plan_path,
                engine=str(payload.get("engine") or "system_say"),
                voice=str(payload.get("voice") or "Tingting"),
                rate=int(payload.get("rate") or 175),
                mp3=True,
                overwrite=True,
                credentials_file=DEFAULT_VOLCENGINE_CREDENTIALS,
                quality_reference_path=(
                    self.find_reference(str(payload.get("reference_id") or "")).path
                    if self.find_reference(str(payload.get("reference_id") or ""))
                    else None
                ),
                quality_threshold=float(payload.get("quality_threshold") or 0.9),
                pitch_rate=int(payload.get("pitch_rate") if payload.get("pitch_rate") is not None else -6),
                speech_rate=int(payload.get("speech_rate") or 0),
                max_self_check_attempts=int(payload.get("max_self_check_attempts") or 12),
                strict_quality_gate=bool(payload.get("strict_quality_gate", True)),
                seedvc_repo_path=str(payload.get("seedvc_repo") or DEFAULT_SEEDVC_REPO),
                seedvc_python=(str(payload.get("seedvc_python") or "") or None),
                seedvc_model=str(payload.get("seedvc_model") or "v2"),
                seedvc_source_voice=str(payload.get("seedvc_source_voice") or "Tingting"),
                seedvc_diffusion_steps=int(payload.get("seedvc_diffusion_steps") or 30),
                seedvc_similarity=float(payload.get("seedvc_similarity") or 0.85),
                seedvc_intelligibility=float(payload.get("seedvc_intelligibility") or 0.7),
                seedvc_convert_style=bool(payload.get("seedvc_convert_style", False)),
            )
            self.send_json(
                {
                    "ok": True,
                    "message": (
                        f"自检闭环完成：{result.summary['rendered']} 条进入成品，"
                        f"{result.summary['quality_passed']} 条质量通过，"
                        f"{result.summary['held_for_review']} 条被拦截，"
                        f"{result.summary['quality_review']} 条待复核，{result.summary['failed']} 条失败。"
                    ),
                    "result": asdict(result),
                    "preview_segments": render_manifest_segments_with_outputs(
                        {"segments": [asdict(item) for item in result.segments]},
                        allowed_root=self.server.output_dir,
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001
            self.send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_open_path(self) -> None:
        try:
            payload = self.read_json()
            raw_path = str(payload.get("path") or "")
            reveal = bool(payload.get("reveal", False))
            target = resolve_allowed_path(raw_path, [self.server.output_dir, self.server.reference_dir])
            if target is None:
                self.send_error_json("这个路径不在配音工具允许打开的目录里。", HTTPStatus.BAD_REQUEST)
                return
            if not target.exists():
                self.send_error_json("文件还没生成，暂时没有可打开的输出。", HTTPStatus.NOT_FOUND)
                return
            open_local_path(target, reveal=reveal)
            self.send_json({"ok": True, "path": str(target)})
        except Exception as exc:  # noqa: BLE001
            self.send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_reference_template(self) -> None:
        try:
            payload = self.read_json()
            requested_ids = [str(item) for item in payload.get("reference_ids", [])]
            reference_map = {item.id: item for item in self.server.references()}
            selected = [reference_map[item_id] for item_id in requested_ids if item_id in reference_map]
            if len(selected) < 2:
                self.send_error_json("请至少勾选两条参考音频。", HTTPStatus.BAD_REQUEST)
                return
            output_path = self.server.generated_reference_dir / f"voice_template_{time.strftime('%Y%m%d_%H%M%S')}.wav"
            create_reference_template([Path(item.path) for item in selected], output_path)
            reference = build_audio_reference(output_path, self.server.generated_reference_dir, id_prefix="template")
            duration = reference.duration_seconds or 0
            warning = ""
            if duration < 14:
                warning = "当前模板仍短于14秒，建议再加一条素材。"
            self.send_json(
                {
                    "ok": True,
                    "message": f"已拼接 {len(selected)} 条素材，模板时长 {duration:.2f} 秒。{warning}",
                    "reference": asdict(reference),
                    "warning": warning,
                }
            )
        except subprocess.CalledProcessError as exc:
            self.send_error_json((exc.stderr or str(exc)).strip(), HTTPStatus.INTERNAL_SERVER_ERROR)
        except Exception as exc:  # noqa: BLE001
            self.send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def stream_audio(self, query: str) -> None:
        params = parse_qs(query)
        reference = self.find_reference(params.get("id", [""])[0])
        if reference is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        path = Path(reference.path)
        self.stream_file(path)

    def stream_output_audio(self, query: str) -> None:
        params = parse_qs(query)
        raw_path = params.get("path", [""])[0]
        path = resolve_allowed_path(unquote(raw_path), [self.server.output_dir])
        if path is None or not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.stream_file(path)

    def stream_file(self, path: Path) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with path.open("rb") as handle:
            self.wfile.write(handle.read())

    def find_reference(self, ref_id: str) -> AudioReference | None:
        for reference in self.server.references():
            if reference.id == ref_id:
                return reference
        return None

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body or "{}")

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        data = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, message: str, status: HTTPStatus) -> None:
        self.send_json({"ok": False, "error": message}, status=status)

    def log_message(self, format: str, *args: Any) -> None:
        return


def render_app_html() -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CPtools Voice Lab</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f2eb;
      --panel: #fffdf8;
      --ink: #1f2428;
      --muted: #687076;
      --line: #d8d0c2;
      --blue: #245f73;
      --green: #446b4c;
      --red: #a14035;
      --field: #fbfaf6;
      --shadow: 0 16px 38px rgba(40, 34, 26, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif;
      letter-spacing: 0;
    }}
    button, input, textarea, select {{ font: inherit; }}
    .app {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(260px, 340px) minmax(420px, 1fr) minmax(260px, 360px);
      gap: 1px;
      background: var(--line);
    }}
    aside, main {{
      background: var(--panel);
      min-width: 0;
    }}
    .sidebar, .inspector {{
      padding: 22px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    main {{
      padding: 24px;
      display: grid;
      grid-template-rows: auto auto 1fr;
      gap: 18px;
    }}
    .topbar {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
    }}
    h1, h2, h3, p {{ margin: 0; }}
    h1 {{ font-size: 22px; line-height: 1.25; }}
    h2 {{ font-size: 15px; }}
    h3 {{ font-size: 13px; color: var(--muted); font-weight: 650; }}
    .sub {{ color: var(--muted); font-size: 13px; margin-top: 6px; line-height: 1.45; }}
    .pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 7px 10px;
      font-size: 12px;
      color: var(--muted);
      white-space: nowrap;
    }}
    .field {{ display: grid; gap: 7px; }}
    label {{ font-size: 12px; color: var(--muted); font-weight: 650; }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid var(--line);
      background: var(--field);
      color: var(--ink);
      border-radius: 8px;
      padding: 10px 11px;
      outline: none;
    }}
    textarea {{
      min-height: 230px;
      resize: vertical;
      line-height: 1.5;
    }}
    input:focus, textarea:focus, select:focus {{ border-color: var(--blue); box-shadow: 0 0 0 3px rgba(36, 95, 115, 0.12); }}
    .button-row {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
    .btn {{
      border: 1px solid var(--blue);
      background: var(--blue);
      color: white;
      border-radius: 8px;
      padding: 10px 13px;
      cursor: pointer;
      min-height: 40px;
    }}
    .btn.secondary {{ background: transparent; color: var(--blue); }}
    .btn:disabled {{ opacity: .45; cursor: not-allowed; }}
    .mini-btn {{
      border: 1px solid var(--line);
      background: #ffffff;
      color: var(--blue);
      border-radius: 7px;
      padding: 6px 8px;
      cursor: pointer;
      font-size: 12px;
      min-height: 30px;
    }}
    .mini-btn:disabled {{ opacity: .5; cursor: not-allowed; }}
    .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .reference-list {{
      display: grid;
      gap: 8px;
      overflow: auto;
      max-height: calc(100vh - 260px);
      padding-right: 4px;
    }}
    .ref {{
      border: 1px solid var(--line);
      background: #fffaf0;
      border-radius: 8px;
      padding: 10px;
      text-align: left;
      cursor: pointer;
      display: grid;
      gap: 5px;
    }}
    .ref.active {{ border-color: var(--green); background: #f0f6ed; }}
    .ref strong {{
      font-size: 13px;
      overflow-wrap: anywhere;
    }}
    .meta {{ color: var(--muted); font-size: 12px; }}
    audio {{ width: 100%; }}
    .panel {{
      border: 1px solid var(--line);
      background: #fffaf0;
      border-radius: 8px;
      padding: 13px;
      display: grid;
      gap: 10px;
    }}
    .status {{
      border-left: 4px solid var(--green);
      background: #eef5eb;
      padding: 11px 12px;
      border-radius: 6px;
      color: #263b29;
      font-size: 13px;
      line-height: 1.45;
    }}
    .status.error {{ border-left-color: var(--red); background: #f8e9e6; color: #5c2721; }}
    .table {{
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: auto;
      background: white;
      min-height: 180px;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 9px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); background: #f9f5ee; position: sticky; top: 0; }}
    td {{ overflow-wrap: anywhere; }}
    .model-list {{ display: grid; gap: 10px; }}
    .model {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fbfaf6;
    }}
    .model strong {{ font-size: 13px; }}
    .path {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; overflow-wrap: anywhere; }}
    .result-actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .output-cell {{ min-width: 210px; display: grid; gap: 6px; }}
    .empty-audio {{ color: var(--muted); font-size: 12px; }}
    @media (max-width: 1080px) {{
      .app {{ grid-template-columns: 300px 1fr; }}
      .inspector {{ grid-column: 1 / -1; border-top: 1px solid var(--line); }}
    }}
    @media (max-width: 760px) {{
      .app {{ display: block; }}
      .reference-list {{ max-height: 320px; }}
      .grid2 {{ grid-template-columns: 1fr; }}
      main, .sidebar, .inspector {{ padding: 16px; }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div>
        <h1>CPtools Voice Lab</h1>
        <p class="sub">本地人工测试版。参考音频来自 {html.escape(str(DEFAULT_REFERENCE_DIR))}。</p>
      </div>
      <div class="field">
        <label for="search">搜索参考音频</label>
        <input id="search" placeholder="闫妮 / 叶童 / R1_03">
      </div>
      <div class="panel">
        <h2>当前参考音</h2>
        <div id="selectedMeta" class="meta">正在读取参考音频...</div>
        <audio id="player" controls preload="none"></audio>
        <button class="mini-btn" id="mixToggleBtn">加入模板素材篮</button>
      </div>
      <div class="panel">
        <h2>模板素材篮</h2>
        <div id="mixSummary" class="meta">尚未加入素材。</div>
        <div class="button-row">
          <button class="mini-btn" id="mixCreateBtn" disabled>拼接为14～30秒模板</button>
          <button class="mini-btn" id="mixClearBtn">清空</button>
        </div>
      </div>
      <div class="reference-list" id="references"></div>
    </aside>

    <main>
      <div class="topbar">
        <div>
          <h1>CPtools 真实配音</h1>
          <p class="sub">已接入豆包 TTS 与 Seed-VC 音色替换：先做表演，再换目标音色，并统一进入自检。</p>
        </div>
        <div class="pill" id="refCount">0 条参考音</div>
      </div>

      <div class="grid2">
        <div class="field">
          <label for="projectName">项目名</label>
          <input id="projectName" value="voice_test">
        </div>
        <div class="field">
          <label for="provider">模型路线</label>
          <select id="provider">
            <option value="volcengine_doubao_tts" selected>豆包声音复刻2.0（真实生成）</option>
            <option value="seedvc_conversion">Seed-VC 音色替换</option>
            <option value="cosyvoice3_local">CosyVoice3 本地</option>
            <option value="modelscope_cosyvoice3_api">ModelScope CosyVoice3 API</option>
            <option value="xfyun_tts_clone">讯飞声音复刻</option>
          </select>
        </div>
        <div class="field">
          <label for="renderRoute">生成路线</label>
          <select id="renderRoute">
            <option value="volcengine_clone" selected>豆包 TTS 直接复刻</option>
            <option value="seedvc_conversion">Seed-VC 先表演后换音色</option>
          </select>
        </div>
        <div class="field">
          <label for="speaker">默认角色</label>
          <input id="speaker" value="闫妮">
        </div>
        <div class="field">
          <label for="emotion">情绪/口吻</label>
          <input id="emotion" value="自然、真实、有生活感">
        </div>
        <div class="field">
          <label for="volcengineSpeaker">已训练音色 ID</label>
          <input id="volcengineSpeaker" value="cptoolsauthorizedvoice01">
        </div>
        <div class="field">
          <label for="pitchRate">音调校准（已自测）</label>
          <input id="pitchRate" type="number" min="-12" max="12" value="-6">
        </div>
        <div class="field">
          <label for="seedvcSourceVoice">Seed-VC 源表演声音</label>
          <input id="seedvcSourceVoice" value="Tingting">
        </div>
        <div class="field">
          <label for="seedvcSimilarity">Seed-VC 相似度强度</label>
          <input id="seedvcSimilarity" type="number" min="0" max="1" step="0.05" value="0.85">
        </div>
      </div>

      <div class="field">
        <label for="script">测试台词</label>
        <textarea id="script">闫妮：这事儿吧，咱们得慢慢说，不能光看表面。
旁白：先用参考音频定住声音气质，再生成可检查的配音计划。</textarea>
      </div>

      <div class="field">
        <label for="instruction">导演提示</label>
        <input id="instruction" value="语气不要播音腔，保留口语停顿，像真实对话。">
      </div>

      <div class="button-row">
        <button class="btn" id="planBtn">生成配音计划</button>
        <button class="btn" id="renderBtn" disabled>生成/转换音频</button>
        <button class="btn secondary" id="configBtn">生成配置模板</button>
        <button class="btn secondary" id="latestBtn">加载最新成品批次</button>
      </div>

      <div id="status" class="status">请选择左侧参考音频，然后生成第一版计划。</div>

      <div class="table">
        <table>
          <thead>
            <tr><th>编号</th><th>角色</th><th>台词</th><th>参考音频</th><th>输出文件</th><th>试听输出</th></tr>
          </thead>
          <tbody id="segments"><tr><td colspan="6" class="meta">还没有生成计划。</td></tr></tbody>
        </table>
      </div>
    </main>

    <aside class="inspector">
      <div class="panel">
        <h2>生成结果</h2>
        <div id="paths" class="meta">等待生成。</div>
      </div>
      <div class="panel">
        <h2>模型路线</h2>
        <div class="model-list" id="models"></div>
      </div>
    </aside>
  </div>
  <script>
    const state = {{ references: [], selected: null, models: [], lastResult: null, mixSelection: [] }};
    const $ = (id) => document.getElementById(id);
    const fmtDuration = (s) => s == null ? "未知" : `${{Number(s).toFixed(2)}}s`;
    const fmtAudioMeta = (r) => `${{r.extension.toUpperCase()}} · ${{fmtDuration(r.duration_seconds)}} · ${{r.sample_rate || "?"}} Hz · ${{r.channels || "?"}} ch · ${{r.size_mb}} MB`;

    function setStatus(message, isError=false) {{
      $("status").textContent = message;
      $("status").className = isError ? "status error" : "status";
    }}

    async function loadReferences() {{
      const response = await fetch("/api/references");
      const data = await response.json();
      state.references = data.references || [];
      $("refCount").textContent = `${{state.references.length}} 条参考音`;
      renderReferences();
      const preferred = state.references.find(r => r.name.includes("闫妮参考")) || state.references[0];
      if (preferred) selectReference(preferred.id);
      if (!state.references.length) setStatus("没有读到参考音频，请确认磁盘目录是否在线。", true);
    }}

    async function loadModels() {{
      const response = await fetch("/api/models");
      const data = await response.json();
      state.models = data.models || [];
      $("models").innerHTML = state.models.map(m => `
        <div class="model">
          <strong>${{escapeHtml(m.name)}}</strong>
          <div class="meta">${{escapeHtml(m.fit)}}</div>
          <div class="meta">${{escapeHtml(m.tradeoff)}}</div>
        </div>
      `).join("");
    }}

    function renderReferences() {{
      const query = $("search").value.trim().toLowerCase();
      const items = state.references.filter(r => !query || r.name.toLowerCase().includes(query) || r.relative_path.toLowerCase().includes(query));
      $("references").innerHTML = items.map(r => `
        <button class="ref ${{state.selected && state.selected.id === r.id ? "active" : ""}}" data-id="${{r.id}}">
          <strong>${{escapeHtml(r.name)}}</strong>
          <span class="meta">${{escapeHtml(fmtAudioMeta(r))}}</span>
        </button>
      `).join("") || `<div class="meta">没有匹配的参考音频。</div>`;
      document.querySelectorAll(".ref").forEach(btn => btn.addEventListener("click", () => selectReference(btn.dataset.id)));
    }}

    function selectReference(id) {{
      state.selected = state.references.find(r => r.id === id);
      if (!state.selected) return;
      $("selectedMeta").innerHTML = `<strong>${{escapeHtml(state.selected.name)}}</strong><br>${{escapeHtml(fmtAudioMeta(state.selected))}}`;
      $("player").src = `/audio?id=${{encodeURIComponent(state.selected.id)}}`;
      $("mixToggleBtn").textContent = state.mixSelection.includes(id) ? "从素材篮移除" : "加入模板素材篮";
      renderReferences();
    }}

    function toggleMixSelection() {{
      if (!state.selected) return;
      const index = state.mixSelection.indexOf(state.selected.id);
      if (index >= 0) state.mixSelection.splice(index, 1);
      else state.mixSelection.push(state.selected.id);
      $("mixToggleBtn").textContent = state.mixSelection.includes(state.selected.id) ? "从素材篮移除" : "加入模板素材篮";
      renderMixSummary();
    }}

    function renderMixSummary() {{
      const selected = state.mixSelection.map(id => state.references.find(r => r.id === id)).filter(Boolean);
      const total = selected.reduce((sum, item) => sum + Number(item.duration_seconds || 0), 0) + Math.max(0, selected.length - 1) * 0.15;
      $("mixSummary").innerHTML = selected.length
        ? `${{selected.map((item, index) => `${{index + 1}}. ${{escapeHtml(item.name)}}`).join("<br>")}}<br><strong>预计时长：${{total.toFixed(2)}}s</strong>${{total < 14 ? " · 还需增加素材" : total > 30 ? " · 将自动截至29.8s" : " · 符合训练范围"}}`
        : "尚未加入素材。";
      $("mixCreateBtn").disabled = selected.length < 2;
    }}

    async function createReferenceTemplate() {{
      $("mixCreateBtn").disabled = true;
      try {{
        setStatus("正在统一采样率并拼接模板素材...");
        const response = await fetch("/api/reference-template", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ reference_ids: state.mixSelection }})
        }});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "拼接失败");
        state.references.push(data.reference);
        state.mixSelection = [];
        renderMixSummary();
        selectReference(data.reference.id);
        setStatus(data.message, Boolean(data.warning));
      }} catch (err) {{
        setStatus(err.message, true);
      }} finally {{
        renderMixSummary();
      }}
    }}

    async function generatePlan() {{
      $("planBtn").disabled = true;
      try {{
        const response = await fetch("/api/plan", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            project_name: $("projectName").value,
            provider: $("provider").value,
            speaker: $("speaker").value,
            emotion: $("emotion").value,
            instruction: $("instruction").value,
            script_text: $("script").value,
            reference_id: state.selected ? state.selected.id : ""
          }})
        }});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "生成失败");
        state.lastResult = data.result;
        setStatus(data.message);
        $("paths").innerHTML = `
          <div class="result-actions">
            <button class="mini-btn" data-open-path="${{escapeAttr(data.result.output_dir)}}">打开输出目录</button>
            <button class="mini-btn" data-open-path="${{escapeAttr(data.result.plan_csv_path)}}" data-reveal="1">打开 CSV</button>
            <button class="mini-btn" data-open-path="${{escapeAttr(data.result.plan_json_path)}}" data-reveal="1">打开 JSON</button>
            <button class="mini-btn" data-open-path="${{escapeAttr(data.result.report_markdown_path)}}" data-reveal="1">打开报告</button>
          </div>
          <div>CSV</div><div class="path">${{escapeHtml(data.result.plan_csv_path)}}</div>
          <div>JSON</div><div class="path">${{escapeHtml(data.result.plan_json_path)}}</div>
          <div>报告</div><div class="path">${{escapeHtml(data.result.report_markdown_path)}}</div>
        `;
        bindOpenButtons();
        renderSegments(data.preview_segments || []);
        $("renderBtn").disabled = false;
      }} catch (err) {{
        setStatus(err.message, true);
      }} finally {{
        $("planBtn").disabled = false;
      }}
    }}

    async function renderCurrentPlan() {{
      if (!state.lastResult || !state.lastResult.plan_json_path) {{
        setStatus("请先生成配音计划。", true);
        return;
      }}
      $("renderBtn").disabled = true;
      try {{
        const route = $("renderRoute").value;
        setStatus(route === "seedvc_conversion"
          ? "正在调用 Seed-VC：先生成源表演，再转换到当前参考音色，并做自检..."
          : "正在调用豆包声音复刻2.0：每条会生成多个候选，自动检查AI味、音色和音调，不合格不进成品...");
        const response = await fetch("/api/render", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            plan_json_path: state.lastResult.plan_json_path,
            engine: route,
            voice: $("volcengineSpeaker").value,
            pitch_rate: Number($("pitchRate").value),
            speech_rate: 0,
            quality_threshold: 0.90,
            max_self_check_attempts: 12,
            strict_quality_gate: true,
            seedvc_model: "v2",
            seedvc_source_voice: $("seedvcSourceVoice").value,
            seedvc_similarity: Number($("seedvcSimilarity").value),
            seedvc_intelligibility: 0.7,
            seedvc_diffusion_steps: 30,
            seedvc_convert_style: false,
            reference_id: state.selected ? state.selected.id : ""
          }})
        }});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "渲染失败");
        setStatus(data.message);
        $("paths").innerHTML += `
          <div>渲染清单 CSV</div><div class="path">${{escapeHtml(data.result.manifest_csv_path)}}</div>
          <div>渲染清单 JSON</div><div class="path">${{escapeHtml(data.result.manifest_json_path)}}</div>
        `;
        renderSegments(data.preview_segments || []);
      }} catch (err) {{
        setStatus(err.message, true);
      }} finally {{
        $("renderBtn").disabled = false;
      }}
    }}

    async function writeConfig() {{
      $("configBtn").disabled = true;
      try {{
        const response = await fetch("/api/config-template", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ provider: $("provider").value }})
        }});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "配置生成失败");
        setStatus(`配置模板已生成：${{data.path}}`);
      }} catch (err) {{
        setStatus(err.message, true);
      }} finally {{
        $("configBtn").disabled = false;
      }}
    }}

    async function loadLatestRender() {{
      try {{
        const response = await fetch("/api/latest-render");
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "加载失败");
        state.lastResult = null;
        setStatus(data.message);
        $("paths").innerHTML = `
          <div class="result-actions">
            <button class="mini-btn" data-open-path="${{escapeAttr(data.result.output_dir)}}">打开输出目录</button>
            <button class="mini-btn" data-open-path="${{escapeAttr(data.result.manifest_csv_path)}}" data-reveal="1">打开清单 CSV</button>
            <button class="mini-btn" data-open-path="${{escapeAttr(data.result.manifest_json_path)}}" data-reveal="1">打开清单 JSON</button>
          </div>
          <div>输出目录</div><div class="path">${{escapeHtml(data.result.output_dir)}}</div>
          <div>渲染清单</div><div class="path">${{escapeHtml(data.result.manifest_json_path)}}</div>
        `;
        bindOpenButtons();
        renderSegments(data.preview_segments || []);
      }} catch (err) {{
        setStatus(err.message, true);
      }}
    }}

    function renderSegments(segments) {{
      $("segments").innerHTML = segments.map(s => `
        <tr>
          <td>${{escapeHtml(s.id)}}</td>
          <td>${{escapeHtml(s.speaker)}}</td>
          <td>${{escapeHtml(s.text)}}</td>
          <td class="path">${{escapeHtml(s.reference_audio || "")}}</td>
          <td class="path">${{escapeHtml(s.output_file || "")}}</td>
          <td>
            <div class="output-cell">
              ${{s.output_audio_url ? `<audio controls preload="none" src="${{escapeAttr(s.output_audio_url)}}"></audio>` : `<span class="empty-audio">${{s.status === "held_for_review" ? "自检拦截，未进入成品" : "尚未生成音频"}}</span>`}}
              ${{s.status ? `<span class="meta">状态：${{escapeHtml(s.status)}}</span>` : ""}}
              ${{s.quality_status ? `<span class="meta">质量：${{escapeHtml(s.quality_status)}}${{s.quality_score != null ? ` · ${{Number(s.quality_score).toFixed(4)}}` : ""}}${{s.quality_artifact_risk != null ? ` · AI味风险 ${{Number(s.quality_artifact_risk).toFixed(4)}}` : ""}}</span>` : ""}}
              ${{s.quality_attempts ? `<span class="meta">自检候选：${{escapeHtml(String(s.quality_attempts))}} 次 · 音调 ${{escapeHtml(String(s.selected_pitch_rate ?? ""))}}</span>` : ""}}
              ${{s.selected_text_variant && s.selected_text_variant !== "original" ? `<span class="meta">节奏自修正：${{escapeHtml(variantLabel(s.selected_text_variant))}}</span>` : ""}}
              ${{s.vc_model ? `<span class="meta">VC：${{escapeHtml(s.vc_model)}}${{s.vc_similarity != null ? ` · 相似度 ${{Number(s.vc_similarity).toFixed(2)}}` : ""}}</span>` : ""}}
              ${{s.source_pitch_shift_semitones != null ? `<span class="meta">源表演降调：${{Number(s.source_pitch_shift_semitones).toFixed(1)}} 半音</span>` : ""}}
              ${{s.source_audio_path ? `<span class="meta">源表演：${{escapeHtml(s.source_audio_path)}}</span>` : ""}}
              ${{Array.isArray(s.quality_flags) && s.quality_flags.length ? `<span class="meta">原因：${{escapeHtml(s.quality_flags.join(", "))}}</span>` : ""}}
              ${{s.output_audio_path ? `<button class="mini-btn" data-open-path="${{escapeAttr(s.output_audio_path)}}" data-reveal="1">打开位置</button>` : ""}}
            </div>
          </td>
        </tr>
      `).join("") || `<tr><td colspan="6" class="meta">没有台词段落。</td></tr>`;
      bindOpenButtons();
    }}

    function variantLabel(value) {{
      const labels = {{
        first_comma_as_sentence: "首个逗号改句号",
        clause_pause: "短语加停顿",
        mid_pause: "中段加停顿"
      }};
      return labels[value] || value;
    }}

    function bindOpenButtons() {{
      document.querySelectorAll("[data-open-path]").forEach(btn => {{
        if (btn.dataset.boundOpen === "1") return;
        btn.dataset.boundOpen = "1";
        btn.addEventListener("click", () => openPath(btn.dataset.openPath, btn.dataset.reveal === "1"));
      }});
    }}

    async function openPath(path, reveal=false) {{
      try {{
        const response = await fetch("/api/open-path", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ path, reveal }})
        }});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "打开失败");
        setStatus(`已打开：${{data.path}}`);
      }} catch (err) {{
        setStatus(err.message, true);
      }}
    }}

    function escapeHtml(value) {{
      return String(value).replace(/[&<>"']/g, ch => ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }}[ch]));
    }}

    function escapeAttr(value) {{
      return escapeHtml(value).replace(/`/g, "&#96;");
    }}

    $("search").addEventListener("input", renderReferences);
    $("mixToggleBtn").addEventListener("click", toggleMixSelection);
    $("mixCreateBtn").addEventListener("click", createReferenceTemplate);
    $("mixClearBtn").addEventListener("click", () => {{ state.mixSelection = []; renderMixSummary(); }});
    $("planBtn").addEventListener("click", generatePlan);
    $("renderBtn").addEventListener("click", renderCurrentPlan);
    $("configBtn").addEventListener("click", writeConfig);
    $("latestBtn").addEventListener("click", loadLatestRender);
    loadReferences();
    loadModels();
  </script>
</body>
</html>"""


def run_voice_app(
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
) -> None:
    server = VoiceAppServer((host, port), reference_dir=reference_dir, output_dir=output_dir)
    url = f"http://{host}:{server.server_address[1]}"
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    print(f"CPtools Voice Lab: {url}", flush=True)
    print(f"Reference dir: {server.reference_dir}", flush=True)
    print(f"Output dir: {server.output_dir}", flush=True)
    server.serve_forever()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cp-tools voice app")
    parser.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_voice_app(
        reference_dir=args.reference_dir,
        output_dir=args.output_dir,
        host=args.host,
        port=args.port,
        open_browser=args.open,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
