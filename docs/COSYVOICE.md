# CosyVoice 集成方案

## 上游能力

项目对接官方 `QwenAudio/CosyVoice` 仓库。当前 README 推荐 Fun-CosyVoice 3.0，并说明它支持多语言与跨语言零样本音色克隆、流式合成、情绪/语速/音量等指令控制。官方仓库提供 FastAPI 服务及以下接口：

- `/inference_zero_shot`：文本 + 提示文本 + 参考音频；
- `/inference_cross_lingual`：文本 + 参考音频；
- `/inference_instruct2`：文本 + 指令 + 参考音频；
- `/inference_sft` 与 `/inference_instruct`：预置说话人模式。

本项目 v0.1 只调用 `/inference_zero_shot`。CosyVoice 作为独立 GPU 服务运行，中台不复制其源码和模型权重，通过 `COSYVOICE_BASE_URL` 调用。这降低许可证耦合，也避免把重型推理环境塞入中台主进程。

## 启动中台

```bash
python -m venv .venv
pip install -e .
uvicorn lifecontext_api.main:app --app-dir apps/api --reload --port 8000
```

CosyVoice 按其官方 README 单独安装并启动 FastAPI 服务，默认地址为 `http://127.0.0.1:50000`。

## 调用顺序

1. 创建 Person；
2. 为具体目的创建 VoiceConsent；
3. 调用 `/v1/persons/{id}/voice/synthesize`，同时提交 `consent_id`、完全相同的 `purpose`、参考音频及其准确文本；
4. 中台校验授权后调用 CosyVoice；
5. 将上游返回的 PCM 包装成 WAV 返回。

## 安全边界

- 只允许克隆本人声音或已有明确授权的声音；
- 授权目的、有效期和是否允许保存参考音频分别记录；
- v0.1 默认不保存上传的参考音频；
- 公开生成内容应提供“合成语音”标识；
- 后续应加入撤销、审计、水印/溯源和反冒用检测；
- 人格授权与音色授权相互独立，拥有 `SOUL.md` 不代表拥有声音使用权。

## 已知工程约束

- 本地包装服务使用 SoundFile 读取参考 WAV，再通过 TorchAudio 重采样；避免新版 `torchaudio.load` 强制依赖 TorchCodec 导致试听失败。音频读取回归验证使用 `.runtime\cosyvoice-venv\Scripts\python.exe tests/test_cosyvoice_audio.py`。
- 官方推理环境以 Python 3.10、Conda、SoX 和 GPU 容器为主要路径；
- 模型权重体积和显存需求不适合随中台默认安装；
- 上游 FastAPI 示例返回裸 `int16` PCM，本项目适配器将其包装为 22050 Hz 单声道 WAV；若更换模型导致采样率变化，需将采样率改成服务端元数据，而不是写死。
- 当前骨架尚未实现登录、租户隔离、速率限制与加密，不能直接暴露到公网。
