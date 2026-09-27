"""Maintainer-only WAV generation using an existing, separate Kokoro environment.

Run with that environment's Python and pass --model and --voices. The application
ships only the resulting PCM files; it never imports or downloads a TTS model.
"""
import argparse
import json
from pathlib import Path

# Each project's manifest is the vocabulary and preserves its existing WAV IDs.
NUMBER_BLOCKS = tuple(digit + unit for unit in '十百千万' for digit in '一二三四五六七八九')
NUMBER_PARTS = (*'零一二三四五六七八九十百千万亿点负', '米', '公里', '地图单位', *NUMBER_BLOCKS)


def infer(engine, phonemes, voice, speed=1.):
    import numpy as np
    tokens = engine.tokenizer.tokenize(phonemes)
    if not 0 < len(tokens) <= 510:
        raise ValueError('语音片段的音素数量无效')
    inputs = {item.name: item.type for item in engine.sess.get_inputs()}
    token_key = 'input_ids' if 'input_ids' in inputs else 'tokens'
    speed_type = np.int32 if inputs['speed'] == 'tensor(int32)' else np.float32
    if speed_type == np.int32 and speed != int(speed):
        raise ValueError('数字生成需要支持浮点语速的新版模型导出')
    outputs = engine.sess.run(None, {
        token_key: np.array([[0, *tokens, 0]], dtype=np.int64),
        'style': np.asarray(engine.voices[voice][len(tokens) - 1], dtype=np.float32),
        'speed': np.array([speed], dtype=speed_type),
    })
    values = dict(zip((item.name for item in engine.sess.get_outputs()), outputs))
    return np.asarray(outputs[0]).ravel(), values.get('duration'), len(tokens)


def numeric_samples(engine, g2p, text, voice):
    """Keep the complete numeral in a spoken carrier, including boundary pauses."""
    import numpy as np
    if 'duration' not in {item.name for item in engine.sess.get_outputs()}:
        raise ValueError('数字生成需要带 duration 输出的 Kokoro v1.0 模型导出，见语音包 SOURCES.md')
    prefix, word, suffix = g2p('现在读数') + ', ', g2p(text), ', ' + g2p('读数结束') + '.'
    audio, durations, count = infer(engine, prefix + word + suffix, voice, .8)
    durations = np.asarray(durations).ravel()
    if len(durations) != count + 2 or np.any(durations <= 0) or len(audio) != sum(durations) * 600:
        raise ValueError('数字音频的模型时间边界无效')
    edges = np.r_[0, np.cumsum(durations)].astype(int) * 600
    begin = 1 + len(engine.tokenizer.tokenize(prefix))
    end = begin + len(engine.tokenizer.tokenize(word))
    # Keep the adjacent comma/space frames: hard phoneme cuts lose consonants.
    # Exclude the suffix's space so the following carrier syllable cannot leak.
    samples = audio[edges[begin - 2]:edges[end + 1]]
    return np.r_[np.zeros(480), samples, np.zeros(480)], 24000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--voices', required=True)
    parser.add_argument('--output', default=str(Path(__file__).resolve().parents[1] / 'wardogs_audio/assets/default'))
    parser.add_argument('--refresh-numbers', action='store_true', help='重制数字、完整数词及距离单位，保留其他已有录音')
    args = parser.parse_args()
    import numpy as np
    import soundfile as sf
    import onnxruntime as ort
    from kokoro_onnx import Kokoro
    from misaki.zh import ZHG2P
    options = ort.SessionOptions(); options.intra_op_num_threads = 4
    session = ort.InferenceSession(args.model, sess_options=options, providers=['CPUExecutionProvider'])
    metadata = session.get_modelmeta().custom_metadata_map
    config = json.loads(metadata['kokoro_config']) if 'kokoro_config' in metadata else None
    engine = Kokoro.from_session(session, args.voices, vocab_config=config)
    g2p = ZHG2P()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    vocabulary = json.loads((Path(__file__).resolve().parents[1] / 'wardogs_audio/assets/default/manifest.json').read_text(encoding='utf-8'))
    for i, text in enumerate(NUMBER_BLOCKS):
        vocabulary['entries']['zh-CN'][text] = f'zh-CN-number-{i+1:03}.wav'
    entries = {}
    punctuation = str.maketrans({'，': ',', '。': '.', '！': '!', '？': '?'})
    for language, texts in vocabulary['entries'].items():
        voice = vocabulary['voices'][language]
        lang = 'zh' if language == 'zh-CN' else 'en-us'
        entries[language] = {}
        for text, filename in texts.items():
            target = root / filename
            entries[language][text] = filename
            numeric = language == 'zh-CN' and text in NUMBER_PARTS
            if not target.is_file() or (numeric and args.refresh_numbers):
                if numeric:
                    samples, rate = numeric_samples(engine, g2p, text, voice)
                else:
                    phonemes = g2p(text.translate(punctuation)) if language == 'zh-CN' else engine.tokenizer.phonemize(text, lang)
                    samples, _, _ = infer(engine, phonemes, voice)
                    rate = 24000
                if len(samples) < rate * .08 or np.max(np.abs(samples)) < .005:
                    raise ValueError('Empty audio: ' + text)
                if not numeric:
                    audible = np.flatnonzero(np.abs(samples) > .006)
                    start = max(0, audible[0] - int(rate * .025))
                    end = min(len(samples), audible[-1] + int(rate * .045))
                    samples = samples[start:end]
                sf.write(str(target), samples, rate, subtype='PCM_16')
            print(filename + ' ' + text, flush=True)
    (root / 'manifest.json').write_text(json.dumps(dict(version=1, sample_rate=24000,
        generator='Kokoro-82M v1.0 / kokoro-onnx', voices=vocabulary['voices'],
        entries=entries), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
