"""음악의 템포(BPM)와 비트 위치 찾기 — numpy만 사용.

1. 스펙트럼 변화량(spectral flux)으로 '소리가 튀는 정도(onset 강도)' 곡선을 만들고
2. 자기상관으로 가장 그럴듯한 박자 간격(템포)을 고른 뒤
3. 동적 계획법(Ellis 2007)으로 onset이 강하면서 간격이 일정한 비트 위치를 찾는다.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 22050
N_FFT = 2048
HOP = 512
# 분석 창이 소리보다 조금 먼저 반응하는 만큼 보정 (합성 드럼으로 측정한 값)
ONSET_LATENCY = 0.019
LOW_BAND_EMPHASIS = 0.15


@dataclass
class BeatResult:
    bpm: float
    beats: list[float]      # 초 단위 비트 위치
    duration: float


def onset_envelope(y: np.ndarray, sr: int = SAMPLE_RATE) -> np.ndarray:
    """프레임별 onset 강도 (프레임 간격 = HOP / sr 초)."""
    if len(y) < N_FFT:
        y = np.pad(y, (0, N_FFT - len(y)))
    # 프레임 중심을 맞추기 위해 앞뒤로 반 프레임 패딩
    y = np.pad(y, (N_FFT // 2, N_FFT // 2))
    n_frames = 1 + (len(y) - N_FFT) // HOP
    window = np.hanning(N_FFT).astype(np.float32)
    fb = _mel_filterbank(sr)
    # 저음 대역(킥·베이스)에 가중치 → 엇박 하이햇보다 정박을 잡는다
    band_w = np.exp(-np.arange(fb.shape[0]) / (fb.shape[0] * LOW_BAND_EMPHASIS))
    band_w /= band_w.sum()
    env = np.zeros(n_frames, dtype=np.float32)
    prev = None
    # 긴 곡도 메모리를 적게 쓰도록 블록 단위로 처리
    block = 512
    for b0 in range(0, n_frames, block):
        b1 = min(n_frames, b0 + block)
        idx = np.arange(b0, b1)[:, None] * HOP + np.arange(N_FFT)[None, :]
        frames = y[idx] * window
        mag = np.abs(np.fft.rfft(frames, axis=1))
        logmag = np.log1p(100.0 * (mag @ fb.T))
        if prev is None:
            diff = np.diff(logmag, axis=0, prepend=logmag[:1])
        else:
            diff = np.diff(np.vstack([prev, logmag]), axis=0)
        env[b0:b1] = np.maximum(diff, 0) @ band_w
        prev = logmag[-1:]
    # 느린 변화(음량 변화)를 빼서 순간적인 변화만 남긴다
    win = max(1, int(round(sr / HOP * 0.5)))
    kernel = np.ones(win) / win
    local_mean = np.convolve(env, kernel, mode="same")
    env = np.maximum(env - local_mean, 0)
    std = env.std()
    return env / std if std > 0 else env


def _mel_filterbank(sr: int, n_mels: int = 64, fmax: float = 8000.0) -> np.ndarray:
    """삼각형 mel 필터 (저음 대역을 더 촘촘하게 → 킥/베이스 박자를 잘 잡는다)."""
    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel2hz(m):
        return 700.0 * (10 ** (m / 2595.0) - 1.0)

    freqs = np.fft.rfftfreq(N_FFT, 1.0 / sr)
    pts = mel2hz(np.linspace(hz2mel(30.0), hz2mel(min(fmax, sr / 2)), n_mels + 2))
    fb = np.zeros((n_mels, len(freqs)), dtype=np.float32)
    for i in range(n_mels):
        lo, mid, hi = pts[i], pts[i + 1], pts[i + 2]
        up = (freqs - lo) / max(mid - lo, 1e-9)
        down = (hi - freqs) / max(hi - mid, 1e-9)
        fb[i] = np.maximum(0, np.minimum(up, down))
    return fb


def estimate_tempo(env: np.ndarray, sr: int = SAMPLE_RATE, min_bpm: float = 60,
                   max_bpm: float = 200, prior_bpm: float = 120) -> float:
    fps = sr / HOP
    if len(env) < 4 or not env.any():
        return 0.0
    x = env - env.mean()
    n = len(x)
    # FFT로 자기상관 계산
    size = 1 << int(np.ceil(np.log2(2 * n)))
    f = np.fft.rfft(x, size)
    ac = np.fft.irfft(f * np.conj(f), size)[:n]
    ac /= ac[0] if ac[0] else 1
    min_lag = max(1, int(np.floor(fps * 60 / max_bpm)))
    max_lag = min(n - 2, int(np.ceil(fps * 60 / min_bpm)))
    if max_lag <= min_lag:
        return 0.0
    lags = np.arange(min_lag, max_lag + 1)
    bpms = 60 * fps / lags
    # 사람이 자주 듣는 템포(120 근처)를 약간 선호 (log-gaussian)
    prior = np.exp(-0.5 * (np.log2(bpms / prior_bpm) / 1.0) ** 2)
    score = ac[lags].copy()
    score *= prior
    i = int(np.argmax(score))
    lag = float(lags[i])
    # 포물선 보간으로 lag를 소수점까지 다듬기
    if 0 < i < len(lags) - 1:
        a, b, c = score[i - 1], score[i], score[i + 1]
        denom = a - 2 * b + c
        if denom != 0:
            lag += 0.5 * (a - c) / denom
    return 60 * fps / lag


def track_beats(env: np.ndarray, bpm: float, sr: int = SAMPLE_RATE,
                tightness: float = 100.0) -> np.ndarray:
    """비트 프레임 인덱스 배열."""
    fps = sr / HOP
    if bpm <= 0 or len(env) == 0:
        return np.zeros(0, dtype=int)
    period = 60 * fps / bpm
    # onset을 박자 길이 정도로 부드럽게
    half_w = int(round(period))
    w = np.arange(-half_w, half_w + 1)
    gauss = np.exp(-0.5 * (w * 32.0 / period) ** 2)
    local = np.convolve(env, gauss, mode="same")

    n = len(local)
    score = np.zeros(n)
    backlink = -np.ones(n, dtype=int)
    lo_off = int(round(period / 2))
    hi_off = int(round(2 * period))
    offsets = np.arange(-hi_off, -lo_off + 1)
    penalty = -tightness * np.log(-offsets / period) ** 2
    first = True
    thresh = 0.01 * local.max() if local.max() > 0 else 0
    for t in range(n):
        lo = t + offsets
        valid = lo >= 0
        if first and local[t] < thresh:
            score[t] = local[t]
            continue
        if valid.any():
            cand = score[lo[valid]] + penalty[valid]
            j = int(np.argmax(cand))
            score[t] = local[t] + cand[j]
            backlink[t] = lo[valid][j]
        else:
            score[t] = local[t]
        first = False
    # 끝부분 근처에서 가장 점수가 높은 곳부터 거꾸로 따라가기
    maxes = _local_maxima(score)
    if not maxes.any():
        return np.zeros(0, dtype=int)
    med = np.median(score[maxes])
    cands = np.nonzero(maxes & (score >= 0.5 * med))[0]
    t = int(cands[-1]) if len(cands) else int(np.argmax(score))
    beats = []
    while t >= 0:
        beats.append(t)
        t = int(backlink[t])
    beats = np.array(beats[::-1])
    # 앞뒤 조용한 구간의 의미 없는 비트 제거
    strength = local[beats]
    keep = strength >= 0.5 * np.sqrt(np.mean(local ** 2))
    if keep.any():
        idx = np.nonzero(keep)[0]
        beats = beats[idx[0]: idx[-1] + 1]
    return beats


def _local_maxima(x: np.ndarray) -> np.ndarray:
    m = np.zeros(len(x), dtype=bool)
    if len(x) >= 3:
        m[1:-1] = (x[1:-1] > x[:-2]) & (x[1:-1] >= x[2:])
    return m


def analyze_samples(y: np.ndarray, sr: int = SAMPLE_RATE, bpm_hint: float = 0.0) -> BeatResult:
    duration = len(y) / sr
    env = onset_envelope(y, sr)
    bpm = bpm_hint if bpm_hint > 0 else estimate_tempo(env, sr)
    frames = track_beats(env, bpm, sr)
    beats = [round(float(f * HOP / sr) + ONSET_LATENCY, 4) for f in frames]
    # 실제 비트 간격으로 BPM을 다시 계산 (표시용)
    if len(beats) >= 4 and bpm_hint <= 0:
        # 정수 프레임 간격의 중앙값은 치우치므로 직선 맞춤 기울기로 계산
        slope = float(np.polyfit(np.arange(len(beats)), beats, 1)[0])
        if slope > 0:
            bpm = 60.0 / slope
    return BeatResult(bpm=round(bpm, 1), beats=beats, duration=duration)


def analyze_file(path: str, bpm_hint: float = 0.0) -> BeatResult:
    from .ffmpeg import decode_audio

    y = decode_audio(path, SAMPLE_RATE)
    if len(y) == 0:
        raise ValueError("음악 파일에서 소리를 찾지 못했어요.")
    return analyze_samples(y, SAMPLE_RATE, bpm_hint)


def grid_beats(bpm: float, first_beat: float, duration: float) -> list[float]:
    """BPM을 직접 입력했을 때: 첫 비트부터 일정 간격 비트."""
    if bpm <= 0:
        return []
    step = 60.0 / bpm
    n = int((duration - first_beat) / step) + 1
    return [round(first_beat + i * step, 4) for i in range(max(0, n))]
