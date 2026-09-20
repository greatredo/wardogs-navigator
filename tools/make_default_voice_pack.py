"""Maintainer-only WAV generation using an existing, separate Kokoro environment.

Run with that environment's Python and pass --model and --voices. The application
ships only the resulting PCM files; it never imports or downloads a TTS model.
"""
import argparse
import json
from pathlib import Path
import sys

ZH = [
    '沿当前道路行驶', '前方', '米', '公里', '地图单位', '接',
    '路口直行', '路口左转', '路口右转', '路口向左前方', '路口向右前方',
    '下个路口右转', '直线', '掉头', '继续前进', '到达目的地', '已到达目的地',
    '左直角', '右直角', '左发卡', '右发卡', '急刹车', '刹车', '坡顶', '颠簸',
    '跳跃', '变窄', '桥梁', '注意', '涉水', '长弯', '收紧', '放开', '别切', '可切',
    '路线已更新', '路线已重新规划', '行驶方向相反，请在安全位置掉头',
    '已到达，请安全掉头，开始去程', '已到达，请安全掉头，开始返程',
    '各位乘客，欢迎乘坐本次航班。我们即将出发，请系好安全带。',
    '各位乘客，欢迎乘坐返程航班。请系好安全带，我们即将返回出发地。',
    '各位乘客，本次航程已完成百分之', '感谢您的乘坐',
    '各位乘客，我们即将抵达目的地。请保持就座，系好安全带。',
    '我们已抵达本次航线终点。感谢您的乘坐。',
    '当前油量百分之', '当前海拔', '速度每小时',
    '欢迎登机。这是飞行员模式的中文试听。',
    '去程', '返程', '百分之', '地面高度',
    *['左' + n for n in '一二三四五六'], *['右' + n for n in '一二三四五六'],
    *'零一二三四五六七八九十百千万亿点负',
]
EN = [
    'Welcome aboard. Please remain seated and fasten your seat belt.',
    'We have completed', 'percent of our flight. Thank you for flying with us.',
    'We are approaching our destination. Please remain seated with your seat belt fastened.',
    'We have reached our destination. Thank you for joining us today.',
    'Welcome aboard. This is the pilot announcement test.',
    'outbound', 'return', 'point', 'minus', 'hundred', 'thousand', 'million',
    'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
    'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen',
    'eighteen', 'nineteen', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety',
]


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
    entries = {}
    punctuation = str.maketrans({'，': ',', '。': '.', '！': '!', '？': '?'})
    for language, texts, voice, lang in [('zh-CN', ZH, 'zf_xiaoxiao', 'zh'), ('en-US', EN, 'af_heart', 'en-us')]:
        entries[language] = {}
        for index, text in enumerate(dict.fromkeys(texts)):
            filename = f'{language}-{index:03}.wav'
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
        generator='Kokoro-82M v1.0 / kokoro-onnx', voices={'zh-CN': 'zf_xiaoxiao', 'en-US': 'af_heart'},
        entries=entries), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
