# 本地 HARNESS 主链路

## 启动

完成 README 中的安装步骤后，在项目根目录执行 `.\.venv\Scripts\lifecontext.exe serve`，再打开本地页面：

`http://127.0.0.1:8787/ui/`

命令在前台启动管理中台，按 `Ctrl+C` 停止；开发时使用 `serve --reload` 自动重载后端代码。点击顶部“运行中心”进入设置页，再按需启动或停止 Qwen3-4B 与 CosyVoice。Qwen 使用 GPU；CosyVoice 被强制放在 CPU 与系统内存中，首次冷启动通常需要约 30 秒。

## 导入

将 `.docx`、`.pdf`、`.txt`、`.md`、`.json`、`.csv`、`.html` 文件复制到根目录的 `RAWDATA`。也可以在 UI 中选择文件，文件同样只会上传到本机的 HARNESS。

旧版 `.doc` 暂不支持，请在 Word 中另存为 `.docx`。扫描型 PDF 暂无 OCR，只有包含文本层的 PDF 可以直接提取。

## 数据流

1. HARNESS 等待文件写入稳定，避免读取尚未复制完的文件。
2. 计算 SHA-256，按内容寻址复制到 `data/archive`；不修改 RAWDATA 原件。
3. 按文档页码、段落、表格行或 JSON 路径生成 Evidence。
4. 如果端侧模型尚未就绪，任务停在 `waiting_model`，不会用低质量摘要冒充 ThoughtCell。
5. 在运行中心启动 Qwen3-4B；模型就绪后，系统自动恢复等待任务并提取 ThoughtCell。
6. Mindcopy 检索 Evidence，通过本地 OpenAI 兼容接口生成带来源回答。

## 本地端口

- LifeContext API 与 UI：`127.0.0.1:8787`
- llama.cpp：`127.0.0.1:8080`
- CosyVoice：`127.0.0.1:50000`

服务只绑定本机回环地址，不对局域网开放。
