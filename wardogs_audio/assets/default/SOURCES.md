# 默认本地语音包

本包由本项目的内置导航/WRC 台词离线生成，提供系统语音不可用时的基础播报。
WAV 为单声道 24 kHz PCM16。运行时只播放音频，不加载模型、不联网、不依赖 Windows 语音包。

- 生成模型：[hexgrad/Kokoro-82M v1.0](https://huggingface.co/hexgrad/Kokoro-82M)，上游声明 Apache-2.0。
- 中文音色：上游通用音色 `zf_xiaoxiao`。
- 离线转换：[kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx)，MIT；中文前端 Misaki。生成环境和模型不随本程序分发。
- 生成脚本：仓库 `tools/make_default_voice_pack.py`，需要已有的独立 Kokoro 环境与本地模型文件。
- 台词及生成音频按本项目 Apache-2.0 条件提供；不代表游戏官方录音。

`manifest.json` 将原始短语映射到音频。完整固定句优先匹配，动态数字按中文位值组合。
未覆盖的自定义文字明确报错，不能用其他内容替代原指令。

## 数字素材维护

0.7.2 重新生成数字与距离单位，并增加“一十”至“九十”、“一百”至“九百”、
“一千”至“九千”、“一万”至“九万”共 36 个完整数词。运行时沿用最长短语匹配，
例如 250 米使用“二百”“五十”“米”，小数部分仍逐位读出。

短数字单独生成可能出现多余音节。脚本以“现在读数，数字，读数结束。”为语境，
根据模型音素时长截取数字，并保留邻近停顿，避免切掉字头或带入后一句。
只在离线生成数字时使用 0.8 倍语速，应用中的语速设置照常生效。

使用同一 Kokoro-82M v1.0 权重的
[带时长输出的官方 ONNX 导出](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1)
（该发布的 `kokoro-v1.0.onnx`），须提供 `duration` 输出并支持浮点 `speed`。
已验证生成环境为 kokoro-onnx 0.5.0、Misaki 0.7.4、ONNX Runtime 1.27.0，
音色文件仍为 `voices-v1.0.bin` 中的 `zf_xiaoxiao`。

```powershell
python tools/make_default_voice_pack.py --model <本地模型路径> --voices <本地音色路径> --refresh-numbers
```

该命令更新数字及单位录音，保留已有其他台词。重制后应检查实际拼接播报中的整数、
含零数值、小数、米/公里和 WRC 连读；仅验证 WAV 格式不能保证读音正确。
模型、生成环境与语音识别验收工具均不加入应用运行依赖或交付包。
