# AI 配音独立子项目交接

日期：2026-07-17

结论先写清楚：Win 端不需要完整 CPtools。

这个交接包已经把 AI 配音能力从 CPtools 主工程里抽成了一个独立 Python 子项目，包名是 `ai_voice`。它可以独立测试、独立跑模型、独立启动本地工具界面；以后如果要放回 CPtools，只需要让 CPtools 调用这个子项目入口即可。

## 当前目标

继续在 Windows + RTX 4090 上推进 AI 配音工具，重点不是复现 CPtools 主工程，而是跑通下面这条生产链路：

1. 整理参考音频，可把多条短素材拼成一个模板。
2. 生成或导入一条“源表演音频”。
3. 用 Seed-VC / 豆包等路线把源表演转换到目标音色。
4. 自动质量检查：音色、音高、能量、节奏、AI 味风险。
5. 只把自检合格或人工确认可用的音频放入成品。

只使用已经授权的目标声音和参考录音。

## 目录结构

```text
handoffs/cptools_voice_seedvc_20260717/
├── ai_voice/
│   ├── cli.py
│   ├── voice.py
│   ├── voice_app.py
│   ├── voice_quality.py
│   ├── voice_render.py
│   ├── voice_seedvc.py
│   └── voice_volcengine.py
├── tests/
│   └── test_voice*.py
├── requirements-minimal.txt
└── README.md
```

不要再找完整 CPtools 代码。这个文件夹本身就是 AI 配音的最小可运行项目。

## 已验证状态

Mac 侧已在本交接目录验证：

```bash
PYTHONPATH=. pytest -q
```

结果：

```text
22 passed in 2.47s
```

所以 Win 端验收标准应改为：

- `pytest -q` 通过；
- `python -m ai_voice voice seedvc-status` 显示 Seed-VC ready；
- 生成一条真实参考音频的样音；
- 用 `voice quality` 或界面自检看候选结果，不再只靠耳朵盲听。

## Windows 本项目安装

进入这个交接目录，例如：

```powershell
cd C:\Users\win\Desktop\Fonts\AI配音相关项目\handoffs\cptools_voice_seedvc_20260717
```

创建或使用已有虚拟环境：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\pip.exe install -r requirements-minimal.txt
```

运行独立测试：

```powershell
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe -m pytest -q
```

预期应是 `22 passed`。如果少量音频相关测试因为没有 ffmpeg 被跳过或失败，先安装 ffmpeg 并确认命令行能直接执行：

```powershell
ffmpeg -version
```

## 独立命令入口

所有命令都从 `ai_voice` 走：

```powershell
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe -m ai_voice voice models
.\.venv\Scripts\python.exe -m ai_voice voice seedvc-status
```

生成配音计划：

```powershell
.\.venv\Scripts\python.exe -m ai_voice voice plan .\script.txt --output-dir .\data\voice_runs
```

启动本地工具界面：

```powershell
.\.venv\Scripts\python.exe -m ai_voice voice app `
  --reference-dir "D:\AI_training\voice_refs" `
  --output-dir "D:\AI_training\voice_runs" `
  --open
```

界面里已有：

- 参考音频列表；
- 输出位置打开；
- 输出音频试听；
- 多条素材拼接成模板；
- 渲染后自检。

## Seed-VC 外部模型

Seed-VC 不放进本项目仓库。它是外部模型工程，建议放在：

```text
D:\AI_training\voice_models\seed-vc
```

本项目通过环境变量连接它：

```powershell
$env:CPTOOLS_SEEDVC_REPO="D:\AI_training\voice_models\seed-vc"
$env:CPTOOLS_SEEDVC_PYTHON="D:\AI_training\voice_models\seed-vc\.venv-seedvc\Scripts\python.exe"
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe -m ai_voice voice seedvc-status
```

说明：变量名里还保留 `CPTOOLS_` 是历史兼容名，不代表要依赖 CPtools 主工程。

## 如果 Windows 直连 GitHub 443 被阻断

先不要被这个卡住。可选方案按优先级：

1. 从 Mac 把已经克隆好的 Seed-VC 目录整体拷到 Windows：

   ```text
   /Volumes/AI_training/AI项目落地验证/voice_models/seed-vc
   → D:\AI_training\voice_models\seed-vc
   ```

2. 如果公司网络有代理，在 Windows 配置 git / pip / huggingface 使用代理。
3. 如果 HTTPS 被阻断但 SSH 可用，尝试 SSH 克隆。
4. 实在不行，先用压缩包、移动硬盘或局域网共享拷贝源码和模型缓存。

不要把 Seed-VC 源码、模型权重、音频素材、密钥、虚拟环境提交进这个 AI 配音仓库。

## Seed-VC Windows 环境建议

在 Seed-VC 自己的目录里创建独立环境：

```powershell
cd D:\AI_training\voice_models\seed-vc
py -3.10 -m venv .venv-seedvc
.\.venv-seedvc\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv-seedvc\Scripts\pip.exe install -r requirements.txt
```

如果 PyTorch / CUDA 没装对，用 PyTorch 官方选择器安装匹配 Windows GPU 的版本。RTX 4090 24GB 很适合这个任务。

验证：

```powershell
$env:CPTOOLS_SEEDVC_REPO="D:\AI_training\voice_models\seed-vc"
$env:CPTOOLS_SEEDVC_PYTHON="D:\AI_training\voice_models\seed-vc\.venv-seedvc\Scripts\python.exe"
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe -m ai_voice voice seedvc-status
```

期望：

```text
ready_for_cli: True
```

## 第一条真实测试路线

Windows 上不要依赖 macOS 的 `say`。真实测试建议使用明确的 `source_audio`：

- 人工录一条有表演感的源音频；
- 或用豆包 SeedICL 2.0 生成一条较自然的源表演；
- 再用 Seed-VC 转到目标参考音色。

计划 JSON 里至少要有：

```json
{
  "source_audio": "D:\\AI_training\\voice_runs\\source_performance.wav",
  "reference_audio": "D:\\AI_training\\voice_refs\\target_template.wav"
}
```

渲染示例：

```powershell
.\.venv\Scripts\python.exe -m ai_voice voice render "D:\AI_training\voice_runs\seedvc_test\plan.json" `
  --engine seedvc_conversion `
  --quality-reference "D:\AI_training\voice_refs\target_template.wav" `
  --quality-threshold 0.80 `
  --seedvc-repo "D:\AI_training\voice_models\seed-vc" `
  --seedvc-python "D:\AI_training\voice_models\seed-vc\.venv-seedvc\Scripts\python.exe" `
  --seedvc-model v2 `
  --seedvc-diffusion-steps 10 `
  --seedvc-similarity 0.85 `
  --seedvc-pitch-shifts 0,-1,-2,-3 `
  --allow-review-output
```

生产批量时去掉 `--allow-review-output`，让自检不通过的候选先进入复查，不直接进成品。

## 质量检查命令

```powershell
.\.venv\Scripts\python.exe -m ai_voice voice quality `
  "D:\AI_training\voice_refs\target_template.wav" `
  "D:\AI_training\voice_runs\candidate.wav" `
  --output-dir "D:\AI_training\voice_runs\quality" `
  --min-score 0.80
```

当前质量检查是声学代理指标，不是真正的演员身份识别模型。它适合挡掉明显“AI味重、不像、音高漂、能量平”的候选，但最终仍需要人工听审。

## 当前路线判断

目前更靠谱的路线不是“30 秒从零训练”，而是：

```text
源表演音频（豆包/人工/其他 TTS）
→ Seed-VC 音色转换
→ 自动自检筛选
→ 人工最终听审
```

原因：

- 单纯 TTS 声音会更顺，但演员相似度不稳定；
- Seed-VC 更擅长把“表演”迁移到目标音色；
- 如果源表演太平，转换后仍会平，所以工具设计必须允许替换、拼接、挑选源表演；
- 参考音频太短时，可以把多条干净片段拼成模板，但不要混入噪声、背景音乐或多人声。

## Git 本地提交注意

如果 Windows 端已经暂存但没有 Git 作者信息，先配置：

```powershell
git config user.name "win"
git config user.email "win@example.com"
```

然后再提交。邮箱可以换成实际团队邮箱；不要把密钥、模型、素材提交进去。

