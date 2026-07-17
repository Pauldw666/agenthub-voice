# Seed-VC 下载与 Windows 安装说明

这份说明给 Win 端使用。不要从 Mac 本地路径“猜怎么拷”，直接按下面地址下载。

## 官方地址

Seed-VC 源码官方 GitHub：

```text
https://github.com/Plachtaa/seed-vc.git
```

浏览器 zip 下载地址：

```text
https://github.com/Plachtaa/seed-vc/archive/refs/heads/main.zip
```

当前 Mac 侧验证过的 Seed-VC commit：

```text
51383ef
```

Seed-VC 模型权重官方 Hugging Face：

```text
https://huggingface.co/Plachta/Seed-VC
```

官方 README 说明：模型会在第一次推理时自动从 Hugging Face 下载。如果 Hugging Face 网络不通，可在命令前设置：

```powershell
$env:HF_ENDPOINT="https://hf-mirror.com"
```

## 方式一：Git 克隆源码

```powershell
New-Item -ItemType Directory -Force "D:\AI_training\voice_models" | Out-Null
cd D:\AI_training\voice_models
git clone https://github.com/Plachtaa/seed-vc.git
cd seed-vc
```

如果要锁到 Mac 侧验证过的版本：

```powershell
git checkout 51383ef
```

## 方式二：浏览器下载 zip

如果命令行 git 被拦，但浏览器能打开 GitHub：

1. 打开：

   ```text
   https://github.com/Plachtaa/seed-vc/archive/refs/heads/main.zip
   ```

2. 解压到：

   ```text
   D:\AI_training\voice_models\seed-vc
   ```

3. 确认这个目录下能看到：

   ```text
   inference.py
   inference_v2.py
   requirements.txt
   configs\
   modules\
   ```

## Windows 环境安装

建议 Seed-VC 使用自己的虚拟环境，不要和 AI 配音工具的 `.venv` 混在一起。

```powershell
cd D:\AI_training\voice_models\seed-vc
py -3.10 -m venv .venv-seedvc
.\.venv-seedvc\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv-seedvc\Scripts\pip.exe install -r requirements.txt
```

如果需要 Hugging Face 镜像：

```powershell
$env:HF_ENDPOINT="https://hf-mirror.com"
```

如果 CUDA / PyTorch 没装对，到 PyTorch 官方选择器选择 Windows + pip + CUDA 对应版本，再在 `.venv-seedvc` 里安装。

## 连接到 AI 配音工具

回到 AI 配音交接目录：

```powershell
cd C:\Users\win\Desktop\Fonts\AI配音相关项目\handoffs\cptools_voice_seedvc_20260717
$env:PYTHONPATH="."
$env:CPTOOLS_SEEDVC_REPO="D:\AI_training\voice_models\seed-vc"
$env:CPTOOLS_SEEDVC_PYTHON="D:\AI_training\voice_models\seed-vc\.venv-seedvc\Scripts\python.exe"
.\.venv\Scripts\python.exe -m ai_voice voice seedvc-status
```

预期看到：

```text
ready_for_cli: True
```

## 如果 Win 机器 GitHub/Hugging Face 都访问不了

那就不要在 AI 配音代码仓库里硬塞 Seed-VC。正确选择是：

1. 用浏览器、代理或公司网络下载官方 zip。
2. 用单独的 Release、网盘、内网文件服务分发一个 Seed-VC 压缩包。
3. 压缩包只放源码和必要配置；不要包含 `.venv-seedvc`、`checkpoints`、缓存、音频素材和密钥。

原因：Mac 本机 Seed-VC 目录约 2.9GB，里面包含虚拟环境和模型缓存，直接进 Git 会导致仓库巨大、拉取慢、历史污染，并且第三方源码和模型权重也不应该混进我们的 AI 配音主仓库。

