# LifeContext Frontend

这是一个无构建依赖的本地前端原型。

## 打开方式

完整运行请双击项目根目录的 `START_LIFECONTEXT.cmd`；它会启动本地后端并打开页面。仅查看视觉原型时也可以直接双击 `index.html`。

## 已实现的原型交互

- 中英文切换，并保存本地语言偏好
- 总览、资料入口、时间线、数字自我、Mindcopy、L1 评测和设置页面
- RAWDATA 文件夹监听，以及 Word、PDF、TXT、Markdown、JSON、CSV、HTML 导入
- 文件选择与拖拽上传到本地 RAWDATA
- ThoughtCell 审核反馈
- 人生阶段滑块
- Mindcopy 对话模拟和浏览器语音预览
- 本地运行中心：真实启动、停止并轮询 Qwen3-4B 与 CosyVoice 状态
- Qwen 使用 GPU 推理；CosyVoice 使用 CPU/系统内存，避免争抢显存
- 搜索界面、评测运行和导出反馈
- 桌面、平板和移动端响应式布局

## 后续 API 接入点

HARNESS 进度、Evidence/ThoughtCell 数量、Mindcopy 对话和本地模型运行控制已经接入 FastAPI。样例人生时间线与 L1 评测仍用于展示后续产品形态。
