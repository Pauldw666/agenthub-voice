"""Standalone command line entry points for the AI voice subproject."""

from __future__ import annotations

import argparse
from pathlib import Path

from .voice import build_voice_plan, model_options, write_provider_config_template
from .voice_app import DEFAULT_OUTPUT_DIR as VOICE_APP_DEFAULT_OUTPUT_DIR
from .voice_app import DEFAULT_REFERENCE_DIR, run_voice_app
from .voice_quality import analyze_voice_similarity
from .voice_render import render_voice_plan
from .voice_seedvc import DEFAULT_SEEDVC_REPO, check_seedvc_ready


def parse_float_list(value: str) -> tuple[float, ...]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("expected a comma-separated float list")
    try:
        return tuple(float(item) for item in items)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a comma-separated float list") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cptools-voice")
    subparsers = parser.add_subparsers(dest="command", required=True)

    voice_parser = subparsers.add_parser("voice", help="AI dubbing and voice plan utilities.")
    voice_subparsers = voice_parser.add_subparsers(dest="voice_command", required=True)

    voice_plan = voice_subparsers.add_parser(
        "plan",
        help="Convert a script, SRT, CSV, or JSON voice sheet into a provider-neutral dubbing plan.",
    )
    voice_plan.add_argument("input", type=Path, help="Script input: .txt, .md, .srt, .csv, or .json.")
    voice_plan.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/voice"),
        help="Directory for voice plan CSV/JSON/Markdown files.",
    )
    voice_plan.add_argument(
        "--provider",
        default="cosyvoice3_local",
        help="Target provider id, e.g. cosyvoice3_local, modelscope_cosyvoice3_api, volcengine_doubao_tts, xfyun_tts_clone.",
    )
    voice_plan.add_argument("--project-name", default=None, help="Project label used in output file names.")
    voice_plan.add_argument("--default-speaker", default="narrator", help="Speaker name for lines without a prefix.")

    voice_config = voice_subparsers.add_parser(
        "config-template",
        help="Write a provider config template for the next synthesis adapter step.",
    )
    voice_config.add_argument("--provider", default="cosyvoice3_local", help="Provider id to template.")
    voice_config.add_argument(
        "--output",
        type=Path,
        default=Path("data/reports/voice/provider_config.json"),
        help="Output JSON config path.",
    )

    voice_subparsers.add_parser("models", help="List recommended model/provider routes for AI Voice.")

    voice_render = voice_subparsers.add_parser("render", help="Render a voice plan into wav/mp3 audio files.")
    voice_render.add_argument("plan_json", type=Path, help="Voice plan JSON produced by the plan command or app.")
    voice_render.add_argument(
        "--engine",
        default="system_say",
        choices=["system_say", "volcengine_clone", "seedvc_conversion"],
        help="Rendering engine. seedvc_conversion converts a source performance into the target reference voice.",
    )
    voice_render.add_argument("--voice", default="Tingting", help="macOS voice name or Volcengine speaker_id.")
    voice_render.add_argument("--rate", type=int, default=175, help="Speech rate for system_say.")
    voice_render.add_argument(
        "--credentials-file",
        type=Path,
        default=Path(".secrets/volcengine.env"),
        help="Local Volcengine credential env file.",
    )
    voice_render.add_argument("--quality-reference", type=Path, default=None, help="Reference audio for quality gating.")
    voice_render.add_argument("--quality-threshold", type=float, default=0.9)
    voice_render.add_argument("--pitch-rate", type=int, default=-6, help="SeedICL pitch correction, calibrated default -6.")
    voice_render.add_argument("--speech-rate", type=int, default=0)
    voice_render.add_argument("--max-self-check-attempts", type=int, default=12)
    voice_render.add_argument(
        "--allow-review-output",
        action="store_true",
        help="Copy the best reviewed candidate to output even if the self-check gate fails.",
    )
    voice_render.add_argument("--seedvc-repo", type=Path, default=DEFAULT_SEEDVC_REPO)
    voice_render.add_argument("--seedvc-python", default=None)
    voice_render.add_argument("--seedvc-model", default="v2", choices=["v1", "v2"])
    voice_render.add_argument("--seedvc-source-voice", default="Tingting")
    voice_render.add_argument("--seedvc-diffusion-steps", type=int, default=30)
    voice_render.add_argument("--seedvc-similarity", type=float, default=0.85)
    voice_render.add_argument("--seedvc-intelligibility", type=float, default=0.7)
    voice_render.add_argument("--seedvc-convert-style", action="store_true")
    voice_render.add_argument("--seedvc-pitch-shifts", type=parse_float_list, default=(0.0, -2.0, -4.0, 2.0))
    voice_render.add_argument("--no-mp3", action="store_true", help="Only write wav files.")
    voice_render.add_argument("--no-overwrite", action="store_true", help="Skip files that already exist.")

    voice_subparsers.add_parser("seedvc-status", help="Check the external Seed-VC runtime and dependencies.")

    voice_quality = voice_subparsers.add_parser(
        "quality",
        help="Compare a candidate voice output against its reference audio.",
    )
    voice_quality.add_argument("reference", type=Path, help="Reference/template audio.")
    voice_quality.add_argument("candidate", type=Path, help="Generated candidate audio.")
    voice_quality.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/voice_quality"),
        help="Directory for quality report files.",
    )
    voice_quality.add_argument("--min-score", type=float, default=0.9, help="Review threshold for the proxy score.")

    voice_app = voice_subparsers.add_parser("app", help="Start the local AI Voice Lab for manual reference-audio testing.")
    voice_app.add_argument(
        "--reference-dir",
        type=Path,
        default=DEFAULT_REFERENCE_DIR,
        help="Folder containing reference wav/mp3 files.",
    )
    voice_app.add_argument(
        "--output-dir",
        type=Path,
        default=VOICE_APP_DEFAULT_OUTPUT_DIR,
        help="Folder for generated voice plans and provider templates.",
    )
    voice_app.add_argument("--host", default="127.0.0.1", help="Local bind address.")
    voice_app.add_argument("--port", type=int, default=8765, help="Local port.")
    voice_app.add_argument("--open", action="store_true", help="Open the app in the default browser.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "voice" and args.voice_command == "plan":
        result = build_voice_plan(
            input_path=args.input,
            output_dir=args.output_dir,
            provider=args.provider,
            project_name=args.project_name,
            default_speaker=args.default_speaker,
        )
        print(f"Input: {result.input_path}")
        print(f"Provider: {result.provider}")
        print(f"Segments: {result.summary['segments']}")
        print(f"Speakers: {result.summary['speakers']}")
        print(f"Characters: {result.summary['total_characters']}")
        print(f"Missing reference audio: {result.summary['missing_reference_audio']}")
        print(f"Plan CSV: {result.plan_csv_path}")
        print(f"Plan JSON: {result.plan_json_path}")
        print(f"Report Markdown: {result.report_markdown_path}")
        return 0

    if args.command == "voice" and args.voice_command == "config-template":
        config_path = write_provider_config_template(args.output, provider=args.provider)
        print(f"Provider: {args.provider}")
        print(f"Config template: {config_path}")
        return 0

    if args.command == "voice" and args.voice_command == "models":
        for option in model_options():
            print(f"{option['id']}: {option['name']}")
            print(f"  Fit: {option['fit']}")
            print(f"  Strength: {option['strength']}")
            print(f"  Tradeoff: {option['tradeoff']}")
        return 0

    if args.command == "voice" and args.voice_command == "render":
        result = render_voice_plan(
            plan_json_path=args.plan_json,
            engine=args.engine,
            voice=args.voice,
            rate=args.rate,
            mp3=not args.no_mp3,
            overwrite=not args.no_overwrite,
            credentials_file=args.credentials_file,
            quality_reference_path=args.quality_reference,
            quality_threshold=args.quality_threshold,
            pitch_rate=args.pitch_rate,
            speech_rate=args.speech_rate,
            max_self_check_attempts=args.max_self_check_attempts,
            strict_quality_gate=not args.allow_review_output,
            seedvc_repo_path=args.seedvc_repo,
            seedvc_python=args.seedvc_python,
            seedvc_model=args.seedvc_model,
            seedvc_source_voice=args.seedvc_source_voice,
            seedvc_diffusion_steps=args.seedvc_diffusion_steps,
            seedvc_similarity=args.seedvc_similarity,
            seedvc_intelligibility=args.seedvc_intelligibility,
            seedvc_convert_style=args.seedvc_convert_style,
            seedvc_pitch_shifts=args.seedvc_pitch_shifts,
        )
        print(f"Plan JSON: {result.plan_json_path}")
        print(f"Output dir: {result.output_dir}")
        print(f"Engine: {result.summary['engine']}")
        print(f"Voice: {result.summary['voice']}")
        print(f"Segments: {result.summary['segments']}")
        print(f"Rendered: {result.summary['rendered']}")
        print(f"Skipped: {result.summary['skipped']}")
        print(f"Failed: {result.summary['failed']}")
        print(f"Held for review: {result.summary['held_for_review']}")
        print(f"Quality passed: {result.summary['quality_passed']}")
        print(f"Quality review: {result.summary['quality_review']}")
        print(f"Manifest CSV: {result.manifest_csv_path}")
        print(f"Manifest JSON: {result.manifest_json_path}")
        return 1 if result.summary["failed"] or result.summary["held_for_review"] else 0

    if args.command == "voice" and args.voice_command == "seedvc-status":
        status = check_seedvc_ready()
        for key in sorted(status):
            print(f"{key}: {status[key]}")
        return 0 if status.get("ready_for_cli") else 1

    if args.command == "voice" and args.voice_command == "quality":
        result = analyze_voice_similarity(
            reference_path=args.reference,
            candidate_path=args.candidate,
            output_dir=args.output_dir,
            min_score=args.min_score,
        )
        print(f"Reference: {result.reference_path}")
        print(f"Candidate: {result.candidate_path}")
        print(f"Status: {result.status}")
        print(f"Overall proxy score: {result.summary['overall_proxy_score']}")
        print(f"Timbre proxy: {result.summary['timbre_logmel_similarity']}")
        print(f"Pitch score: {result.summary['pitch_score']}")
        print(f"Report JSON: {result.report_json_path}")
        return 0 if result.status == "pass" else 1

    if args.command == "voice" and args.voice_command == "app":
        run_voice_app(
            reference_dir=args.reference_dir,
            output_dir=args.output_dir,
            host=args.host,
            port=args.port,
            open_browser=args.open,
        )
        return 0

    parser.error("Unknown command")
    return 2

