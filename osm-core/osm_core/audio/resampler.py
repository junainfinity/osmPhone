"""
resampler.py - Audio Resampling

This module implements PY-001.8 from the osmPhone architecture.
It resamples incoming 8kHz SCO audio to 16kHz for STT models, and 
downsamples 24kHz/16kHz TTS audio to 8kHz for SCO injection.
"""

import numpy as np

class AudioResampler:
    """
    Utility class for resampling 1D audio sequences using linear interpolation.
    """
    
    @staticmethod
    def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """
        Resample a 1D audio array from orig_sr to target_sr.
        Returns the resampled audio array.
        """
        if orig_sr == target_sr:
            return audio
            
        if len(audio) == 0:
            return np.array([], dtype=audio.dtype)
            
        duration = len(audio) / orig_sr
        num_target_samples = int(duration * target_sr)
        
        # Original time indices
        orig_indices = np.arange(len(audio)) / orig_sr
        
        # Target time indices
        target_indices = np.arange(num_target_samples) / target_sr
        
        # Interpolate
        resampled_audio = np.interp(target_indices, orig_indices, audio)
        
        return resampled_audio.astype(audio.dtype)
