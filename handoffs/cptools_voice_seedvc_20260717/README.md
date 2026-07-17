# CPtools Voice Windows Handoff

Date: 2026-07-17

## Goal

Continue CPtools AI dubbing work on a Windows NVIDIA machine. The Mac side has proved the pipeline and added Seed-VC as an external voice-conversion backend. The next target is GPU-speed A/B testing:

- Doubao SeedICL 2.0 TTS baseline
- Seed-VC voice conversion route
- Later: F5-TTS, GPT-SoVITS, CosyVoice local

Use only authorized target voices and authorized reference recordings.

## Current Repo

Workspace on Mac:

`/Users/dw/Documents/CPtools开发`

Important changed files:

- `src/cptools/voice_seedvc.py`
- `src/cptools/voice_render.py`
- `src/cptools/voice_app.py`
- `src/cptools/cli.py`
- `tests/test_voice_seedvc.py`
- `tests/test_voice_render.py`

Validation on Mac:

```bash
PYTHONPATH=src pytest -q
```

Result:

`63 passed in 2.39s`

## What Was Added

### Seed-VC External Adapter

`src/cptools/voice_seedvc.py` calls an external Seed-VC checkout rather than vendoring GPL project code into CPtools.

It provides:

- `check_seedvc_ready()`
- `convert_with_seedvc()`
- `build_seedvc_command()`

Environment variables:

- `CPTOOLS_SEEDVC_REPO`
- `CPTOOLS_SEEDVC_PYTHON`

### New Render Engine

`render_voice_plan(..., engine="seedvc_conversion")`

Pipeline:

1. Use `source_audio`/`performance_audio` from the plan if present.
2. Otherwise create a temporary source performance with macOS `say` on Mac. On Windows, prefer explicit `source_audio`; do not depend on `say`.
3. Run Seed-VC source-to-target conversion.
4. Run the existing CPtools quality gate.
5. Copy only passing candidates into final output unless `--allow-review-output` is used.

### Seed-VC Pitch Candidates

Seed-VC now tries source-performance pitch shifts and keeps the best candidate.

Default:

`0,-2,-4,2`

CLI:

```bash
--seedvc-pitch-shifts 0,-1,-2,-3
```

The render manifest records:

- `source_audio_path`
- `source_pitch_shift_semitones`
- `vc_model`
- `vc_similarity`
- `selected_candidate_path`
- `quality_score`
- `quality_artifact_risk`
- `quality_flags`

## Mac Seed-VC Smoke Test

External Seed-VC checkout on Mac:

`/Volumes/AI_training/AI项目落地验证/voice_models/seed-vc`

Mac venv:

`/Volumes/AI_training/AI项目落地验证/voice_models/seed-vc/.venv-cptools/bin/python`

Status command:

```bash
CPTOOLS_SEEDVC_PYTHON='/Volumes/AI_training/AI项目落地验证/voice_models/seed-vc/.venv-cptools/bin/python' \
PYTHONPATH=src python3 -m cptools voice seedvc-status
```

Result:

`ready_for_cli: True`

Seed-VC V2 example conversion succeeded:

`/Volumes/AI_training/AI项目落地验证/voice_runs/seedvc_smoke/vc_v2_source_s1_s1p1_1.0_10_0.85.wav`

Quality against Seed-VC example target:

- overall proxy: `0.893`
- timbre proxy: `0.9637`
- pitch score: `0.8619`

## Our Current Voice Findings

The previous pure Doubao TTS batch became less AI-like, but still did not sound like the target actor enough.

Cause found:

- Current target actor reference material is too thin.
- For `闫妮`, available detected material was only about `17.49s` total.
- The only long-ish sample was around `13.22s`.
- Pure TTS can reduce AI flavor but does not reliably capture the specific actor voice.

Seed-VC direction is more promising:

- System `say` source performance -> Seed-VC target reference:
  - timbre proxy got close, but prosody/energy was too flat.
- Doubao self-checked source performance -> Seed-VC target reference:
  - `timbre_logmel_similarity: 0.9769`
  - `overall_proxy_score: 0.8928`
  - blocked mainly for `pitch_drift`

That is why the current code now tries pitch-shifted source-performance candidates.

## Windows Setup Recommendation

Hardware:

- Best: RTX 4090 24GB
- Comfortable: RTX 4080/4070 Ti Super 16GB
- Usable: RTX 3060 12GB or 4060 Ti 16GB
- Avoid for batch production: 8GB VRAM or less

Suggested Windows directory layout:

```text
D:\AI_training\voice_models\seed-vc
D:\AI_training\voice_runs
D:\CPtools开发
```

Clone Seed-VC:

```powershell
cd D:\AI_training\voice_models
git clone https://github.com/Plachtaa/seed-vc.git
```

Create env. Prefer Python 3.10 or 3.11 for Windows:

```powershell
cd D:\AI_training\voice_models\seed-vc
py -3.10 -m venv .venv-cptools
.\.venv-cptools\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv-cptools\Scripts\pip.exe install -r requirements.txt
```

If CUDA torch is not installed correctly, install PyTorch from the official selector for the machine CUDA version.

Then validate from CPtools:

```powershell
$env:CPTOOLS_SEEDVC_REPO="D:\AI_training\voice_models\seed-vc"
$env:CPTOOLS_SEEDVC_PYTHON="D:\AI_training\voice_models\seed-vc\.venv-cptools\Scripts\python.exe"
$env:PYTHONPATH="src"
python -m cptools voice seedvc-status
```

Expected:

`ready_for_cli: True`

## First Windows Test

Use Seed-VC example first:

```powershell
$env:CPTOOLS_SEEDVC_REPO="D:\AI_training\voice_models\seed-vc"
$env:CPTOOLS_SEEDVC_PYTHON="D:\AI_training\voice_models\seed-vc\.venv-cptools\Scripts\python.exe"
$env:PYTHONPATH="src"

python - <<'PY'
from cptools.voice_seedvc import convert_with_seedvc
result = convert_with_seedvc(
    r"D:\AI_training\voice_models\seed-vc\examples\source\source_s1.wav",
    r"D:\AI_training\voice_models\seed-vc\examples\reference\s1p1.wav",
    r"D:\AI_training\voice_runs\seedvc_smoke",
    repo_path=r"D:\AI_training\voice_models\seed-vc",
    python_executable=r"D:\AI_training\voice_models\seed-vc\.venv-cptools\Scripts\python.exe",
    model_version="v2",
    diffusion_steps=10,
    similarity_cfg_rate=0.85,
    intelligibility_cfg_rate=0.7,
    timeout=1800,
)
print(result.output_wav_path)
PY
```

Then run quality:

```powershell
python -m cptools voice quality `
  "D:\AI_training\voice_models\seed-vc\examples\reference\s1p1.wav" `
  "D:\AI_training\voice_runs\seedvc_smoke\<output wav>" `
  --output-dir "D:\AI_training\voice_runs\seedvc_smoke\quality" `
  --min-score 0.80
```

## First Real CPtools Test

Use a target reference template and a source performance audio.

Important: On Windows, do not rely on macOS `say`. Put `source_audio` into the plan JSON. Good source audio can be:

- a human recorded performance,
- a Doubao self-checked TTS performance,
- another clean authorized guide performance.

Example plan segment field:

```json
{
  "source_audio": "D:\\AI_training\\voice_runs\\source_performance.wav",
  "reference_audio": "D:\\AI_training\\voice_refs\\target_template.wav"
}
```

Render:

```powershell
python -m cptools voice render "D:\AI_training\voice_runs\seedvc_test\plan.json" `
  --engine seedvc_conversion `
  --quality-reference "D:\AI_training\voice_refs\target_template.wav" `
  --quality-threshold 0.80 `
  --seedvc-repo "D:\AI_training\voice_models\seed-vc" `
  --seedvc-python "D:\AI_training\voice_models\seed-vc\.venv-cptools\Scripts\python.exe" `
  --seedvc-model v2 `
  --seedvc-diffusion-steps 10 `
  --seedvc-similarity 0.85 `
  --seedvc-pitch-shifts 0,-1,-2,-3 `
  --allow-review-output
```

For production, remove `--allow-review-output` so failed candidates do not enter final output.

## Recommended Next Work

1. Run Seed-VC on Windows GPU with the same Doubao-source probe.
2. Compare pitch-shift candidates and check whether one passes the gate.
3. Add explicit UI support for uploading/selecting `source_audio` per segment.
4. Add F5-TTS as another external backend.
5. Add a real speaker-embedding verifier, not only the current acoustic proxy.
6. Gather better authorized target reference material: multiple clean 20-30s templates beat one short template.

## Known Caveats

- Current quality checker is an acoustic proxy, not a true actor identity verifier.
- Target reference for `闫妮` is currently too short for strong actor identity.
- Seed-VC preserves the source performance. If the source performance is flat or wrong, the result will still feel wrong even if timbre improves.
- Mac can run Seed-VC but is not efficient enough for batch production. Windows + NVIDIA CUDA is the right next machine.
