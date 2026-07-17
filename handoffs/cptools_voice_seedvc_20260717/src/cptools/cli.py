"""Command line entry points for CPtools."""

from __future__ import annotations

import argparse
from pathlib import Path

from .color_reference import create_analyzed_look_package, create_look_package, list_camera_profiles
from .dit_copy import copy_verify
from .dit_manifest import summarize_manifests
from .dit_metadata import export_card_metadata
from .dit_mhl import run_mhl_doctor, write_mhl_doctor_reports
from .dit_scan import scan_dit_source, write_scan_reports
from .dit_stills import DEFAULT_ARRI_LOGC4_REC709_LUT, export_resolve_stills
from .vfx_cdl import split_ale_cdl
from .vfx_plates import IdMode, prepare_vfx_plates
from .vfx_return import plan_vfx_returns
from .vfx_session import ensure_vfx_session_dirs
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
    parser = argparse.ArgumentParser(prog="cp-tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    vfx_parser = subparsers.add_parser("vfx-plates", help="VFX plates utilities.")
    vfx_subparsers = vfx_parser.add_subparsers(dest="vfx_command", required=True)

    prepare = vfx_subparsers.add_parser(
        "prepare",
        help="Convert InstantNoodles xlsx/csv/xml data into clean CSV, JSON, and traffic_light TXT.",
    )
    prepare.add_argument("input", type=Path, help="InstantNoodles .xlsx, .csv, or Excel 2004 .xml file.")
    prepare.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/vfx_plates"),
        help="Directory for generated files.",
    )
    prepare.add_argument(
        "--session-layout",
        action="store_true",
        help="Write outputs under output-dir/YYYYMMDD/plates.",
    )
    prepare.add_argument("--prefix", default="MZR", help="VFX id prefix for generated ids.")
    prepare.add_argument("--start", type=int, default=10, help="First generated VFX id number.")
    prepare.add_argument("--step", type=int, default=10, help="Generated VFX id increment.")
    prepare.add_argument("--digits", type=int, default=4, help="Zero-padding width for generated ids.")
    prepare.add_argument(
        "--stacked-suffix",
        action="store_true",
        help="Use A/B/C suffixes for clips sharing the same record in/out range, usually stacked tracks.",
    )
    prepare.add_argument(
        "--id-mode",
        choices=[mode.value for mode in IdMode],
        default=IdMode.SMART.value,
        help=(
            "How to choose VFX ids: smart keeps existing names that look like VFX ids, "
            "name always keeps Name, auto always generates ids."
        ),
    )

    split_cdl = vfx_subparsers.add_parser(
        "split-cdl",
        help="Split a Resolve ALE_CDL export into per-shot ASC CDL files using CPVFX metadata.",
    )
    split_cdl.add_argument("metadata_csv", type=Path, help="CPVFX metadata CSV with vfx_id/source timecodes.")
    split_cdl.add_argument("ale_cdl", type=Path, help="Resolve EXPORT_ALE_CDL .ale file.")
    split_cdl.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/vfx_plates/cdl"),
        help="Directory for per-shot .cdl files.",
    )
    split_cdl.add_argument(
        "--session-layout",
        action="store_true",
        help="Write outputs under output-dir/YYYYMMDD/CDL.",
    )

    plan_return = vfx_subparsers.add_parser(
        "plan-return",
        help="Scan VFX return files and write a safe conform plan from CPVFX metadata.",
    )
    plan_return.add_argument("metadata_csv", type=Path, help="CPVFX metadata CSV with vfx_id and record timecodes.")
    plan_return.add_argument("return_dir", type=Path, help="Folder containing returned VFX movies or image sequences.")
    plan_return.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/vfx_plates/returns"),
        help="Directory for return plan CSV/JSON reports.",
    )
    plan_return.add_argument(
        "--session-layout",
        action="store_true",
        help="Write outputs under output-dir/YYYYMMDD/视效表格.",
    )
    plan_return.add_argument(
        "--target-track",
        default="auto",
        help="Target return track label for the plan, e.g. auto or V5.",
    )

    color_parser = subparsers.add_parser("color-reference", help="Color reference look pipeline utilities.")
    color_subparsers = color_parser.add_subparsers(dest="color_command", required=True)

    color_subparsers.add_parser("profiles", help="List known camera/profile registry entries.")

    scaffold = color_subparsers.add_parser(
        "scaffold",
        help="Write a first-pass look package with camera profile and editable node tree JSON.",
    )
    scaffold.add_argument("--profile", default="blackmagic_braw_gen5_dwg", help="Camera/profile id.")
    scaffold.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/color_reference"),
        help="Directory for generated look package files.",
    )
    scaffold.add_argument("--package-name", default="look_scout", help="Output file stem.")
    scaffold.add_argument("--working-space", default=None, help="Override working space label.")
    scaffold.add_argument("--display-target", default="Rec.709 Gamma 2.4", help="Output display target label.")

    analyze = color_subparsers.add_parser(
        "analyze",
        help="Analyze a reference/source image pair and write a populated look node tree package.",
    )
    analyze.add_argument("reference", type=Path, help="Reference image path.")
    analyze.add_argument("source", type=Path, help="Source/neutral image path.")
    analyze.add_argument("--profile", default="blackmagic_braw_gen5_dwg", help="Camera/profile id.")
    analyze.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/color_reference"),
        help="Directory for generated look analysis files.",
    )
    analyze.add_argument("--package-name", default="look_analysis", help="Output file stem.")
    analyze.add_argument("--working-space", default=None, help="Override working space label.")
    analyze.add_argument("--display-target", default="Rec.709 Gamma 2.4", help="Output display target label.")

    dit_parser = subparsers.add_parser("dit", help="DIT automation utilities.")
    dit_subparsers = dit_parser.add_subparsers(dest="dit_command", required=True)

    scan = dit_subparsers.add_parser(
        "scan",
        help="Read-only scan of a camera card or day-backup folder.",
    )
    scan.add_argument("source", type=Path, help="Mounted card, day-backup folder, or sound folder to scan.")
    scan.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/dit_scan"),
        help="Directory for JSON, CSV, and Markdown scan reports.",
    )
    copy_verify_parser = dit_subparsers.add_parser(
        "copy-verify",
        help="Copy a small reviewed source to one or more targets and verify SHA-256 checksums.",
    )
    copy_verify_parser.add_argument("source", type=Path, help="Reviewed file or folder to copy.")
    copy_verify_parser.add_argument(
        "--target",
        type=Path,
        action="append",
        required=True,
        help="Copy target root. Repeat for multiple backup targets.",
    )
    copy_verify_parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=Path("data/reports/dit_copy"),
        help="Directory for checksum manifest CSV/JSON.",
    )
    copy_verify_parser.add_argument(
        "--max-gb",
        type=float,
        default=20.0,
        help="Safety limit before refusing copy unless --allow-large is passed.",
    )
    copy_verify_parser.add_argument(
        "--allow-large",
        action="store_true",
        help="Allow copying a source larger than --max-gb after manual review.",
    )
    copy_verify_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite target files. Default blocks existing files with different hashes.",
    )
    copy_verify_parser.add_argument(
        "--hash",
        choices=["md5", "sha256"],
        default="sha256",
        help="Checksum algorithm for verification and checksum file.",
    )
    copy_verify_parser.add_argument(
        "--copy-missing-first",
        action="store_true",
        help="Copy missing target files before running full checksum verification.",
    )
    copy_verify_parser.add_argument(
        "--progress",
        action="store_true",
        help="Print per-file copy and checksum progress.",
    )
    mhl_parser = dit_subparsers.add_parser("mhl", help="MHL / ASC MHL utilities.")
    mhl_subparsers = mhl_parser.add_subparsers(dest="mhl_command", required=True)
    mhl_doctor = mhl_subparsers.add_parser(
        "doctor",
        help="Check whether official ASC MHL tooling is available.",
    )
    mhl_doctor.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/dit_mhl"),
        help="Directory for MHL doctor JSON/Markdown reports.",
    )
    manifest_parser = dit_subparsers.add_parser("manifest", help="DIT manifest summary utilities.")
    manifest_subparsers = manifest_parser.add_subparsers(dest="manifest_command", required=True)
    manifest_summary = manifest_subparsers.add_parser(
        "summarize",
        help="Summarize DIT scan, copy-verify, and MHL doctor JSON reports.",
    )
    manifest_summary.add_argument(
        "--input-dir",
        type=Path,
        action="append",
        required=True,
        help="Directory containing report JSON files. Repeat for multiple directories.",
    )
    manifest_summary.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/dit_manifest"),
        help="Directory for summary JSON/Markdown reports.",
    )
    metadata_parser = dit_subparsers.add_parser("metadata", help="DIT clip metadata export utilities.")
    metadata_subparsers = metadata_parser.add_subparsers(dest="metadata_command", required=True)
    metadata_export = metadata_subparsers.add_parser(
        "export",
        help="Export camera-card clip metadata CSV from ALE, filename, filesystem, ffprobe, and copy manifest.",
    )
    metadata_export.add_argument("source_root", type=Path, help="Camera card/reel folder.")
    metadata_export.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/dit_metadata"),
        help="Directory for metadata CSV and report JSON.",
    )
    metadata_export.add_argument(
        "--backup-root",
        type=Path,
        default=None,
        help="Backup target root containing the copied reel folder.",
    )
    metadata_export.add_argument(
        "--copy-manifest-json",
        type=Path,
        default=None,
        help="copy-verify JSON manifest used to add MD5/copy status columns.",
    )
    stills_parser = dit_subparsers.add_parser("stills", help="DIT still-frame export utilities.")
    stills_subparsers = stills_parser.add_subparsers(dest="stills_command", required=True)
    stills_export = stills_subparsers.add_parser(
        "export",
        help="Export Rec.709 stills for camera clips through DaVinci Resolve Studio.",
    )
    stills_export.add_argument("source_root", type=Path, help="Camera card/reel folder.")
    stills_export.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/dit_stills"),
        help="Directory for still images and manifests.",
    )
    stills_export.add_argument(
        "--frame-mode",
        choices=["begin", "middle", "end", "offset", "percent"],
        default="middle",
        help="Frame selection rule. Middle matches Silverstack's documented default thumbnail position.",
    )
    stills_export.add_argument("--offset-frames", type=int, default=48, help="Frame offset for --frame-mode offset.")
    stills_export.add_argument("--percent", type=float, default=0.5, help="Clip percentage for --frame-mode percent.")
    stills_export.add_argument("--fps", type=float, default=24.0, help="Timeline/still selection frame rate.")
    stills_export.add_argument(
        "--lut",
        default=DEFAULT_ARRI_LOGC4_REC709_LUT,
        help="Resolve-discovered LUT path to apply if ARRI embedded CDL/LUT application is unavailable.",
    )
    stills_export.add_argument("--limit", type=int, default=None, help="Export only the first N clips for validation.")
    stills_export.add_argument(
        "--keep-project",
        action="store_true",
        help="Keep the temporary Resolve project for inspection.",
    )

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
    voice_config.add_argument(
        "--provider",
        default="cosyvoice3_local",
        help="Provider id to template.",
    )
    voice_config.add_argument(
        "--output",
        type=Path,
        default=Path("data/reports/voice/provider_config.json"),
        help="Output JSON config path.",
    )

    voice_subparsers.add_parser("models", help="List recommended model/provider routes for CPtools Voice.")

    voice_render = voice_subparsers.add_parser(
        "render",
        help="Render a voice plan into wav/mp3 audio files.",
    )
    voice_render.add_argument("plan_json", type=Path, help="Voice plan JSON produced by cp-tools voice plan or the app.")
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
    voice_render.add_argument("--allow-review-output", action="store_true", help="Copy the best reviewed candidate to output even if the self-check gate fails.")
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

    voice_app = voice_subparsers.add_parser(
        "app",
        help="Start the local CPtools Voice Lab for manual reference-audio testing.",
    )
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

    if args.command == "vfx-plates" and args.vfx_command == "prepare":
        output_dir = ensure_vfx_session_dirs(args.output_dir).plates if args.session_layout else args.output_dir
        result = prepare_vfx_plates(
            input_path=args.input,
            output_dir=output_dir,
            prefix=args.prefix,
            start=args.start,
            step=args.step,
            digits=args.digits,
            id_mode=IdMode(args.id_mode),
            stacked_suffix=args.stacked_suffix,
        )
        print(f"Input: {result.input_path}")
        print(f"Events: {result.summary['events']}")
        print(f"Warnings: {result.summary['warnings']}")
        print(f"Errors: {result.summary['errors']}")
        print(f"Clean CSV: {result.clean_csv_path}")
        print(f"Metadata CSV: {result.metadata_csv_path}")
        print(f"Report JSON: {result.report_json_path}")
        print(f"traffic_light TXT: {result.traffic_light_txt_path}")
        return 1 if result.summary["errors"] else 0

    if args.command == "vfx-plates" and args.vfx_command == "split-cdl":
        output_dir = ensure_vfx_session_dirs(args.output_dir).cdl if args.session_layout else args.output_dir
        result = split_ale_cdl(
            ale_path=args.ale_cdl,
            metadata_csv_path=args.metadata_csv,
            output_dir=output_dir,
        )
        print(f"Output dir: {result.output_dir}")
        print(f"Metadata rows: {result.summary['metadata_rows']}")
        print(f"ALE rows: {result.summary['ale_rows']}")
        print(f"Matched: {result.summary['matched']}")
        print(f"Missing: {result.summary['missing']}")
        print(f"Written: {result.summary['written']}")
        print(f"Manifest CSV: {result.manifest_csv_path}")
        return 1 if result.summary["missing"] else 0

    if args.command == "vfx-plates" and args.vfx_command == "plan-return":
        output_dir = ensure_vfx_session_dirs(args.output_dir).tables if args.session_layout else args.output_dir
        result = plan_vfx_returns(
            metadata_csv_path=args.metadata_csv,
            return_dir=args.return_dir,
            output_dir=output_dir,
            target_track=args.target_track,
        )
        print(f"Metadata CSV: {result.metadata_csv_path}")
        print(f"Return dir: {result.return_dir}")
        print(f"Metadata rows: {result.summary['metadata_rows']}")
        print(f"Return assets: {result.summary['return_assets']}")
        print(f"Matched: {result.summary['matched']}")
        print(f"Review: {result.summary['review']}")
        print(f"Missing: {result.summary['missing']}")
        print(f"Extra: {result.summary['extra']}")
        print(f"Plan CSV: {result.report_csv_path}")
        print(f"Plan JSON: {result.report_json_path}")
        return 1 if result.summary["review"] or result.summary["missing"] else 0

    if args.command == "color-reference" and args.color_command == "profiles":
        for profile in list_camera_profiles():
            print(
                f"{profile.profile_id}: {profile.vendor} | {profile.camera_model} | "
                f"{profile.log_curve} / {profile.gamut}"
            )
        return 0

    if args.command == "color-reference" and args.color_command == "scaffold":
        result = create_look_package(
            output_dir=args.output_dir,
            profile_id=args.profile,
            working_space=args.working_space,
            display_target=args.display_target,
            package_name=args.package_name,
        )
        print(f"Output dir: {result.output_dir}")
        print(f"Profile: {result.summary['profile']}")
        print(f"Nodes: {result.summary['nodes']}")
        print(f"Profile JSON: {result.profile_json_path}")
        print(f"Node tree JSON: {result.node_tree_json_path}")
        print(f"Report JSON: {result.report_json_path}")
        return 0

    if args.command == "color-reference" and args.color_command == "analyze":
        result = create_analyzed_look_package(
            output_dir=args.output_dir,
            profile_id=args.profile,
            reference_path=args.reference,
            source_path=args.source,
            working_space=args.working_space,
            display_target=args.display_target,
            package_name=args.package_name,
        )
        print(f"Output dir: {result.output_dir}")
        print(f"Profile: {result.summary['profile']}")
        print(f"Nodes: {result.summary['nodes']}")
        print(f"Confidence: {result.summary['confidence']}")
        print(f"Profile JSON: {result.profile_json_path}")
        print(f"Analysis JSON: {result.analysis_json_path}")
        print(f"Node tree JSON: {result.node_tree_json_path}")
        print(f"Report JSON: {result.report_json_path}")
        return 0

    if args.command == "dit" and args.dit_command == "scan":
        result = scan_dit_source(args.source)
        reports = write_scan_reports(result, args.output_dir)
        print(f"Source: {result.root}")
        print(f"Mode: {result.source_mode}")
        print(f"Status: {result.status}")
        print(f"Cards: {result.summary['card_count']}")
        print(f"Sound folders: {result.summary['sound_folder_count']}")
        print(f"Video files: {result.summary['video_files']}")
        print(f"Audio files: {result.summary['audio_files']}")
        print(f"Report JSON: {reports.json_path}")
        print(f"Cards CSV: {reports.csv_path}")
        print(f"Report Markdown: {reports.markdown_path}")
        return 1 if result.status == "RED" else 0

    if args.command == "dit" and args.dit_command == "copy-verify":
        progress_callback = (lambda message: print(message, flush=True)) if args.progress else None
        result = copy_verify(
            source=args.source,
            targets=args.target,
            manifest_dir=args.manifest_dir,
            max_bytes=int(args.max_gb * 1000**3),
            allow_large=args.allow_large,
            overwrite=args.overwrite,
            hash_algorithm=args.hash,
            copy_missing_first=args.copy_missing_first,
            progress_callback=progress_callback,
        )
        print(f"Source: {result.source}")
        print(f"Transfer ID: {result.transfer_id}")
        print(f"Hash: {result.hash_algorithm}")
        print(f"Status: {result.status}")
        print(f"Files: {result.total_files}")
        print(f"Targets: {len(result.targets)}")
        print(f"Total GB: {round(result.total_bytes / 1000**3, 3)}")
        print(f"Manifest CSV: {result.manifest_csv_path}")
        print(f"Manifest JSON: {result.manifest_json_path}")
        print(f"Manifest Markdown: {result.manifest_markdown_path}")
        print(f"Checksum file: {result.checksum_path}")
        return 1 if result.status == "RED" else 0

    if args.command == "dit" and args.dit_command == "mhl" and args.mhl_command == "doctor":
        result = run_mhl_doctor()
        reports = write_mhl_doctor_reports(result, args.output_dir)
        print(f"Status: {result.status}")
        print(f"ascmhl: {result.ascmhl_path or 'not found'}")
        print(f"Report JSON: {reports.json_path}")
        print(f"Report Markdown: {reports.markdown_path}")
        return 0

    if args.command == "dit" and args.dit_command == "manifest" and args.manifest_command == "summarize":
        result = summarize_manifests(input_dirs=args.input_dir, output_dir=args.output_dir)
        print(f"Status: {result.status}")
        print(f"Scan reports: {result.summary['scan_report_count']}")
        print(f"Copy manifests: {result.summary['copy_manifest_count']}")
        print(f"MHL doctor reports: {result.summary['mhl_doctor_report_count']}")
        print(f"Summary JSON: {result.summary_json_path}")
        print(f"Summary Markdown: {result.summary_markdown_path}")
        return 1 if result.status == "RED" else 0

    if args.command == "dit" and args.dit_command == "metadata" and args.metadata_command == "export":
        result = export_card_metadata(
            source_root=args.source_root,
            output_dir=args.output_dir,
            backup_root=args.backup_root,
            copy_manifest_json=args.copy_manifest_json,
        )
        print(f"Source: {result.source_root}")
        print(f"Rows: {result.row_count}")
        print(f"ALE columns: {len(result.ale_columns)}")
        print(f"Metadata CSV: {result.output_csv_path}")
        print(f"Report JSON: {result.report_json_path}")
        return 0

    if args.command == "dit" and args.dit_command == "stills" and args.stills_command == "export":
        result = export_resolve_stills(
            source_root=args.source_root,
            output_dir=args.output_dir,
            frame_mode=args.frame_mode,
            offset_frames=args.offset_frames,
            percent=args.percent,
            fps=args.fps,
            lut_path=args.lut,
            limit=args.limit,
            keep_project=args.keep_project,
        )
        print(f"Source: {result.source_root}")
        print(f"Status: {result.status}")
        print(f"Rows: {len(result.rows)}")
        print(f"Exported: {result.summary['exported']}")
        print(f"Failed: {result.summary['failed']}")
        print(f"Manifest CSV: {result.manifest_csv_path}")
        print(f"Report JSON: {result.report_json_path}")
        return 1 if result.status == "RED" else 0

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
