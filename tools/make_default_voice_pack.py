"""Maintainer-only WAV generation using an existing, separate Kokoro environment.

Run with that environment's Python and pass --model and --voices. The application
ships only the resulting PCM files; it never imports or downloads a TTS model.
"""
import argparse
import json
from pathlib import Path
import sys

# Each project's manifest is the vocabulary and preserves its existing WAV IDs.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--voices', required=True)
    parser.add_argument('--output', default=str(Path(__file__).resolve().parents[1] / 'wardogs_audio/assets/default'))
    args = parser.parse_args()
    import numpy as np
    import soundfile as sf
    from kokoro_onnx import Kokoro
    from misaki.zh import ZHG2P
    engine = Kokoro(args.model, args.voices)
    g2p = ZHG2P()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    vocabulary = json.loads((Path(__file__).resolve().parents[1] / 'wardogs_audio/assets/default/manifest.json').read_text(encoding='utf-8'))
    entries = {}
    punctuation = str.maketrans({'，': ',', '。': '.', '！': '!', '？': '?'})
    for language, texts in vocabulary['entries'].items():
        voice = vocabulary['voices'][language]
        lang = 'zh' if language == 'zh-CN' else 'en-us'
        entries[language] = {}
        for text, filename in texts.items():
            target = root / filename
            entries[language][text] = filename
            if not target.is_file():
                phonemes = g2p(text.translate(punctuation)) if language == 'zh-CN' else engine.tokenizer.phonemize(text, lang)
                samples, rate = engine.create(phonemes, voice=voice, speed=1.0, lang=lang, is_phonemes=True)
                if len(samples) < rate * .08 or np.max(np.abs(samples)) < .005:
                    raise ValueError('Empty audio: ' + text)
                # Trim boundary silence consistently for numerical phrase joins.
                audible = np.flatnonzero(np.abs(samples) > .006)
                start = max(0, audible[0] - int(rate * .025))
                end = min(len(samples), audible[-1] + int(rate * .045))
                sf.write(str(target), samples[start:end], rate, subtype='PCM_16')
            print(filename + ' ' + text, flush=True)
    (root / 'manifest.json').write_text(json.dumps(dict(version=1, sample_rate=24000,
        generator='Kokoro-82M v1.0 / kokoro-onnx', voices=vocabulary['voices'],
        entries=entries), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
