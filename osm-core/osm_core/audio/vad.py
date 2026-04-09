"""
vad.py - Voice Activity Detection

This module implements PY-001.7 from the osmPhone architecture.
It provides a simple energy-based VAD for isolating speech 
from silence before sending segments to the STT engine.
"""

import numpy as np
from typing import List, Tuple

class SimpleVAD:
    """
    A simple Energy-based Voice Activity Detector (VAD).
    """
    def __init__(self, energy_threshold: float = 0.01, min_duration_ms: float = 100.0, frame_duration_ms: float = 30.0):
        self.energy_threshold = energy_threshold
        self.min_duration_ms = min_duration_ms
        self.frame_duration_ms = frame_duration_ms

    def is_speech(self, audio: np.ndarray, sample_rate: int = 16000) -> bool:
        """Determines if the audio array contains speech based on overall energy."""
        if len(audio) == 0:
            return False
        rms = np.sqrt(np.mean(np.square(audio)))
        return bool(rms > self.energy_threshold)

    def get_speech_segments(self, audio: np.ndarray, sample_rate: int = 16000) -> List[Tuple[float, float]]:
        """Returns a list of (start_time, end_time) in seconds of speech boundaries."""
        if len(audio) == 0:
            return []
            
        frame_length = int(sample_rate * (self.frame_duration_ms / 1000.0))
        num_frames = len(audio) // frame_length
        
        segments = []
        in_speech = False
        start_time = 0.0
        
        for i in range(num_frames):
            start_idx = i * frame_length
            end_idx = start_idx + frame_length
            frame = audio[start_idx:end_idx]
            
            rms = np.sqrt(np.mean(np.square(frame)))
            is_frame_speech = rms > self.energy_threshold
            
            current_time = float(start_idx) / sample_rate
            
            if is_frame_speech and not in_speech:
                in_speech = True
                start_time = current_time
            elif not is_frame_speech and in_speech:
                in_speech = False
                end_time = current_time
                if (end_time - start_time) * 1000.0 >= self.min_duration_ms:
                    segments.append((start_time, end_time))
        
        if in_speech:
            end_time = len(audio) / sample_rate
            if (end_time - start_time) * 1000.0 >= self.min_duration_ms:
                segments.append((start_time, end_time))
                
        return segments
