"""
test_vad.py - Tests for VAD module (PY-001.7)
"""
import pytest
import numpy as np
from osm_core.audio.vad import SimpleVAD

def test_silence_detected():
    # UT-PY-001.7-01: 1s of zeros -> is_speech = False
    vad = SimpleVAD()
    audio = np.zeros(16000)
    assert not vad.is_speech(audio, 16000)

def test_speech_detected():
    # UT-PY-001.7-02: 1s of 440Hz sine -> is_speech = True
    vad = SimpleVAD()
    t = np.linspace(0, 1, 16000, endpoint=False)
    audio = 0.5 * np.sin(2 * np.pi * 440 * t)
    assert vad.is_speech(audio, 16000)

def test_segment_boundaries():
    # UT-PY-001.7-03: Speech-silence-speech pattern -> Two segments
    vad = SimpleVAD(min_duration_ms=100.0, frame_duration_ms=30.0)
    sr = 16000
    
    t = np.linspace(0, 0.5, sr // 2, endpoint=False)
    speech = 0.5 * np.sin(2 * np.pi * 440 * t)
    silence = np.zeros(sr // 2)
    
    audio = np.concatenate([speech, silence, speech])
    segments = vad.get_speech_segments(audio, sr)
    
    assert len(segments) == 2
    
    assert 0.0 <= segments[0][0] <= 0.05
    assert 0.45 <= segments[0][1] <= 0.55
    
    assert 0.95 <= segments[1][0] <= 1.05
    assert 1.45 <= segments[1][1] <= 1.55

def test_minimum_duration_filter():
    # UT-PY-001.7-04: 50ms speech blip -> Filtered out
    vad = SimpleVAD(min_duration_ms=100.0)
    sr = 16000
    
    t = np.linspace(0, 0.05, int(sr * 0.05), endpoint=False)
    speech = 0.5 * np.sin(2 * np.pi * 440 * t)
    silence = np.zeros(sr)
    
    audio = np.concatenate([silence, speech, silence])
    segments = vad.get_speech_segments(audio, sr)
    
    assert len(segments) == 0
