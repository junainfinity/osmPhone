"""Voice Activity Detection — Component PY-001.7.

Provides both batch and streaming VAD interfaces:
  - is_speech(audio) -> bool: Check if an audio buffer contains speech (batch).
  - get_speech_segments(audio) -> list: Find speech boundaries in a buffer (batch).
  - process(frame) -> (is_speech, end_of_speech): Feed a single frame for streaming
    detection. Returns whether speech is happening and whether an utterance just ended.

The streaming process() method is what AudioPipeline (PY-001.9) calls on each
incoming PCM frame from the Bluetooth SCO channel. It tracks state internally:
  - Transitions to "in speech" when energy exceeds threshold
  - Transitions to "end of speech" after silence_frames consecutive silent frames
  - Resets for the next utterance after end_of_speech fires

Config integration: reads audio.vad_threshold, audio.min_speech_duration_ms,
and audio.silence_duration_ms from config.yaml when passed to __init__.

FIX LOG (Claude Opus 4.6, 2026-04-09):
  - Added process() streaming method — was missing, causing AttributeError in pipeline
  - Added silence tracking for end-of-speech detection
  - Made thresholds configurable from AudioConfig
"""

import numpy as np
from typing import List, Tuple


class SimpleVAD:
    """Energy-based Voice Activity Detector with both batch and streaming modes."""

    def __init__(
        self,
        energy_threshold: float = 0.01,
        min_duration_ms: float = 100.0,
        frame_duration_ms: float = 30.0,
        silence_duration_ms: float = 700.0,
        sample_rate: int = 16000,
    ):
        self.energy_threshold = energy_threshold
        self.min_duration_ms = min_duration_ms
        self.frame_duration_ms = frame_duration_ms
        self.silence_duration_ms = silence_duration_ms
        self.sample_rate = sample_rate

        # Streaming state for process()
        self._in_speech = False
        self._speech_frames = 0
        self._silence_frames = 0
        # How many consecutive silent frames before we declare end-of-speech
        self._silence_frames_needed = max(1, int(
            silence_duration_ms / frame_duration_ms
        ))
        # Minimum speech frames before we consider it real speech (not a click/pop)
        self._min_speech_frames = max(1, int(
            min_duration_ms / frame_duration_ms
        ))

    # ---- Streaming interface (used by AudioPipeline.feed_audio) ----

    async def process(self, pcm_data: bytes) -> Tuple[bool, bool]:
        """Process a single audio frame for streaming VAD.

        Args:
            pcm_data: Raw PCM bytes (16-bit signed LE assumed, or numpy-compatible).

        Returns:
            (is_speech, end_of_speech):
              - is_speech: True if this frame contains speech.
              - end_of_speech: True if the speaker just stopped talking
                (transitions from speech to silence after enough silent frames).
                This fires exactly once per utterance boundary.
        """
        # Convert bytes to numpy float array for energy calculation
        if isinstance(pcm_data, (bytes, bytearray)):
            audio = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
        else:
            audio = np.asarray(pcm_data, dtype=np.float32)

        if len(audio) == 0:
            return (False, False)

        # Compute RMS energy
        rms = float(np.sqrt(np.mean(np.square(audio))))
        frame_is_speech = rms > self.energy_threshold

        end_of_speech = False

        if frame_is_speech:
            self._speech_frames += 1
            self._silence_frames = 0
            if not self._in_speech and self._speech_frames >= self._min_speech_frames:
                self._in_speech = True
        else:
            if self._in_speech:
                self._silence_frames += 1
                if self._silence_frames >= self._silence_frames_needed:
                    # Speaker stopped — signal end of utterance
                    end_of_speech = True
                    self._in_speech = False
                    self._speech_frames = 0
                    self._silence_frames = 0
            else:
                # Not in speech, silence continues — reset any stray speech frames
                self._speech_frames = 0

        return (self._in_speech or frame_is_speech, end_of_speech)

    def reset(self):
        """Reset streaming state between calls."""
        self._in_speech = False
        self._speech_frames = 0
        self._silence_frames = 0

    # ---- Batch interface (used for offline/segment analysis) ----

    def is_speech(self, audio: np.ndarray, sample_rate: int = 16000) -> bool:
        """Check if an entire audio buffer contains speech based on overall energy."""
        if len(audio) == 0:
            return False
        rms = np.sqrt(np.mean(np.square(audio)))
        return bool(rms > self.energy_threshold)

    def get_speech_segments(self, audio: np.ndarray, sample_rate: int = 16000) -> List[Tuple[float, float]]:
        """Return (start_time, end_time) pairs in seconds of speech regions."""
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
