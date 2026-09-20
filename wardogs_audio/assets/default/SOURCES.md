# 默认本地语音包

本包由本项目的内置导航/WRC 与通用客舱台词离线生成，提供系统语音不可用时的基础播报。
WAV 为单声道 24 kHz PCM16。运行时只播放音频，不加载模型、不联网、不依赖 Windows 语音包。

- 生成模型：[hexgrad/Kokoro-82M v1.0](https://huggingface.co/hexgrad/Kokoro-82M)，上游声明 Apache-2.0。
- 中英文音色：上游通用音色 `zf_xiaoxiao`、`af_heart`。
- 离线转换：[kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx)，MIT；中文前端 Misaki。生成环境和模型不随本程序分发。
- 生成脚本：仓库 `tools/make_default_voice_pack.py`，需要已有的独立 Kokoro 环境与本地模型文件。
- 台词及生成音频按本项目 Apache-2.0 条件提供；不代表航空公司或游戏官方录音。

`manifest.json` 将原始短语映射到音频。完整固定句优先匹配，动态数字按中文位值或英文数词组合。
未覆盖的自定义文字明确报错，不能用其他内容替代原指令。
