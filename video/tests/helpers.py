import wave

import numpy as np


def click_track(bpm: float, duration: float, offset: float = 0.0, sr: int = 22050,
                hihat: float = 0.0, seed: int = 0) -> np.ndarray:
    """킥 드럼(+ 엇박 하이햇) 합성 음원."""
    rng = np.random.default_rng(seed)
    y = 0.01 * rng.standard_normal(int(sr * duration))
    step = 60.0 / bpm
    for i, t in enumerate(np.arange(offset, duration, step)):
        n = int(t * sr)
        tt = np.arange(int(0.12 * sr)) / sr
        kick = np.sin(2 * np.pi * (60 + 80 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 18)
        seg = y[n:n + len(kick)]
        seg += kick[:len(seg)] * (1.0 if i % 2 == 0 else 0.7)
        if hihat:
            m = int((t + step / 2) * sr)
            h = y[m:m + int(0.03 * sr)]
            h += hihat * rng.standard_normal(len(h)) * np.exp(-np.arange(len(h)) / sr * 100)
    return y.astype(np.float32)


def write_wav(path, y: np.ndarray, sr: int) -> None:
    data = (np.clip(y / max(1e-9, np.abs(y).max()) * 0.8, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())
