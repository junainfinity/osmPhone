"""
test_resampler.py - Tests for Audio Resampler (PY-001.8)
"""
import pytest
import numpy as np
from osm_core.audio.resampler import AudioResampler

def test_resample_up():
    # UT-PY-001.8-01: 8kHz to 16kHz
    audio = np.ones(1000)
    res = AudioResampler.resample(audio, 8000, 16000)
    assert len(res) == 2000

def test_resample_down():
    # UT-PY-001.8-02: 16kHz to 8kHz
    audio = np.ones(2000)
    res = AudioResampler.resample(audio, 16000, 8000)
    assert len(res) == 1000

def test_resample_same():
    # UT-PY-001.8-03: Same rate no-op
    audio = np.array([1.0, 2.0, 3.0])
    res = AudioResampler.resample(audio, 16000, 16000)
    assert len(res) == 3
    assert res is audio

def test_resample_preserves_amplitude():
    # UT-PY-001.8-04: Preserves amplitude
    orig_sr = 16000
    target_sr = 8000
    t = np.linspace(0, 1, orig_sr, endpoint=False)
    audio = np.sin(2 * np.pi * 440 * t)
    
    resampled = AudioResampler.resample(audio, orig_sr, target_sr)
    peak_orig = np.max(np.abs(audio))
    peak_resampled = np.max(np.abs(resampled))
    
    diff = abs(peak_orig - peak_resampled)
    assert (diff / peak_orig) < 0.05
