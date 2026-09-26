"""Keep numbers in complete spoken units and preserve contextual audio boundaries."""
import json
from types import SimpleNamespace
import wave

import numpy as np
import pytest

from tools.make_default_voice_pack import NUMBER_PARTS, numeric_samples
from wardogs_audio.pack import DefaultVoicePack


@pytest.mark.parametrize('text,words', [
    ('0米', ['零', '米']),
    ('10米', ['十', '米']),
    ('90米', ['九十', '米']),
    ('100米', ['一百', '米']),
    ('250米', ['二百', '五十', '米']),
    ('1230米', ['一千', '二百', '三十', '米']),
    ('1010米', ['一千', '零', '一十', '米']),
    ('2.5公里', ['二', '点', '五', '公里']),
    ('1.01公里', ['一', '点', '零', '一', '公里']),
    ('10001地图单位', ['一万', '零', '一', '地图单位']),
    ('八百米', ['八百', '米']),
    ('一百米，左三，接，五十米，右六', ['一百', '米', '左三', '接', '五十', '米', '右六']),
])
def test_number_phrases_use_complete_place_values(text, words):
    pack = DefaultVoicePack()
    entries = json.loads((pack.root / 'manifest.json').read_text(encoding='utf-8'))['entries']['zh-CN']
    assert pack.segments(text) == [pack.root / entries[word] for word in words]


def test_all_numeric_assets_are_audible_pcm_without_a_long_carrier():
    pack = DefaultVoicePack()
    for word in NUMBER_PARTS:
        paths = pack.segments(word)
        assert len(paths) == 1, word
        with wave.open(str(paths[0]), 'rb') as audio:
            assert audio.getparams()[:3] == (1, 2, 24000), word
            assert 2400 < audio.getnframes() < 24000 * 2, word
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2')
        assert np.max(np.abs(samples.astype(np.int32))) > 1000, word


def timing_engine(*, duration=True, invalid_timing=False):
    """Distinct fake carrier/word frames expose a wrong crop without a TTS model."""
    def run(_, inputs):
        assert inputs['speed'].dtype == np.float32
        assert inputs['speed'][0] == pytest.approx(.8)
        assert inputs['input_ids'].tolist() == [[0, *map(ord, 'P, AB, S.'), 0]]
        assert inputs['style'].tolist() == [8.]  # Nine phonemes select voice row 8.
        frames = np.array([-9, -9, .1, .2, 1, 2, .3, -9, -9, -9, -9])
        durations = np.ones(len(frames), dtype=np.int64)
        if invalid_timing:
            durations[-1] += 1
        return [np.repeat(frames, 600), durations]
    session = SimpleNamespace(
        get_inputs=lambda: [SimpleNamespace(name='input_ids', type='tensor(int64)'),
                            SimpleNamespace(name='speed', type='tensor(float)')],
        get_outputs=lambda: [SimpleNamespace(name=name) for name in
                             (('waveform', 'duration') if duration else ('waveform',))],
        run=run,
    )
    return SimpleNamespace(sess=session, tokenizer=SimpleNamespace(tokenize=lambda s: list(map(ord, s))),
                           voices={'voice': np.arange(30, dtype=np.float32).reshape(-1, 1)})


def test_numeric_generation_keeps_word_and_pauses_but_excludes_carrier():
    g2p = {'现在读数': 'P', '一百': 'AB', '读数结束': 'S'}.__getitem__
    samples, rate = numeric_samples(timing_engine(), g2p, '一百', 'voice')
    assert rate == 24000
    np.testing.assert_array_equal(samples[:480], 0)
    np.testing.assert_array_equal(samples[-480:], 0)
    np.testing.assert_array_equal(samples[480:-480], np.repeat([.1, .2, 1, 2, .3], 600))


@pytest.mark.parametrize('kwargs', [{'duration': False}, {'invalid_timing': True}])
def test_numeric_generation_rejects_missing_or_inconsistent_timing(kwargs):
    g2p = {'现在读数': 'P', '一百': 'AB', '读数结束': 'S'}.__getitem__
    with pytest.raises(ValueError, match='duration|时间边界'):
        numeric_samples(timing_engine(**kwargs), g2p, '一百', 'voice')
