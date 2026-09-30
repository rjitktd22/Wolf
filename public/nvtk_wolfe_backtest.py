# -*- coding: utf-8 -*-
"""
NVTK Wolfe Symmetry — production backtest
=========================================
Causal ZigZag 0.55% → classic 1-2-3-4 Wolfe wedge (falling = BUY, rising = SELL).
Draws only BUY (green) and SELL (red) rectangles. No entry/exit markers.
Minimum expected travel: 0.40%. Smaller zones are dropped.

Walk-forward on 78,008 NVTK 5-minute bars (2025-09-23 → 2026-09-28):
  432 zones (223 buy / 209 sell)
  67.8% of boxes are later touched
  76.1% of touches then move ≥ 0.40% in the predicted direction
  Out-of-sample (from 2026-05-01): 80.1% hit | touch, payoff 3.74×
  Full sample payoff MFE/MAE = 3.06×

Usage:
  python nvtk_wolfe_backtest.py scaner5_NVTK.xlsx
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd

DEVIATION_PCT = 0.55
ZONE_HALF_RATIO = 0.22
MIN_MOVE_PCT = 0.40
FORWARD_BARS = 48
MIN_IMPULSE_PCT = 0.60
MAX_ATR_RATIO = 2.50
MIN_WAVE_RATIO = 0.45
MAX_WAVE_RATIO = 2.40
MAX_T5_BARS = 48
OVERLAP_GAP = 10


@dataclass
class Pivot:
    idx: int
    time: pd.Timestamp
    price: float
    kind: str
    confirmed_idx: int


@dataclass
class Zone:
    direction: str
    confirm_idx: int
    t0: int
    t1: int
    z_low: float
    z_high: float
    z_mid: float
    expected_pct: float
    score: float


def build_causal_zigzag(df: pd.DataFrame, deviation_pct: float = DEVIATION_PCT) -> List[Pivot]:
    """Confirm a HIGH/LOW only after a reversal of deviation_pct. No lookahead."""
    n = len(df)
    dev = deviation_pct / 100.0
    highs, lows = df["high"].to_numpy(float), df["low"].to_numpy(float)
    times = df["time"].to_numpy()
    pivots: List[Pivot] = []
    last = (highs[0] + lows[0]) / 2.0
    direction = None
    extreme, ex_i = last, 0
    for i in range(1, n):
        h, l = highs[i], lows[i]
        if direction is None:
            if h >= last * (1 + dev):
                direction, extreme, ex_i = "UP", h, i
            elif l <= last * (1 - dev):
                direction, extreme, ex_i = "DOWN", l, i
            continue
        if direction == "UP":
            if h >= extreme:
                extreme, ex_i = h, i
            if l <= extreme * (1 - dev):
                pivots.append(Pivot(ex_i, pd.Timestamp(times[ex_i]), extreme, "HIGH", i))
                last, direction, extreme, ex_i = extreme, "DOWN", l, i
        else:
            if l <= extreme:
                extreme, ex_i = l, i
            if h >= extreme * (1 + dev):
                pivots.append(Pivot(ex_i, pd.Timestamp(times[ex_i]), extreme, "LOW", i))
                last, direction, extreme, ex_i = extreme, "UP", h, i
    clean: List[Pivot] = []
    for p in pivots:
        if clean and p.kind == clean[-1].kind:
            if (p.kind == "HIGH" and p.price > clean[-1].price) or (
                p.kind == "LOW" and p.price < clean[-1].price
            ):
                clean[-1] = p
        elif not clean or p.time > clean[-1].time:
            clean.append(p)
    return clean


def _line(t1, p1, t2, p2, t) -> float:
    dt = t2 - t1
    return p1 if dt == 0 else p1 + (p2 - p1) * ((t - t1) / dt)


def wolfe_zones(df: pd.DataFrame, pivots: List[Pivot]) -> List[Zone]:
    """Classic Wolfe wedge: 4 alternating pivots, converging 1–3 / 2–4 channel.

    BUY  = falling wedge (1 low, 3 ≤ 1, 4 < 2) → green rectangle at projected point 5.
    SELL = rising wedge (inverse) → red rectangle at projected point 5.
    Rectangle height scales with impulse AB (clamped 0.10–0.50% of price).
    """
    atr = df["atr"].to_numpy() if "atr" in df.columns else np.full(len(df), np.nan)
    atr_ratio = df["atr_ratio"].to_numpy() if "atr_ratio" in df.columns else np.full(len(df), np.nan)
    n = len(df)
    out: List[Zone] = []
    for i in range(3, len(pivots)):
        p1, p2, p3, p4 = pivots[i - 3], pivots[i - 2], pivots[i - 1], pivots[i]
        if p1.kind == p2.kind or p2.kind == p3.kind or p3.kind == p4.kind:
            continue
        t1, t2, t3, t4 = p1.idx, p2.idx, p3.idx, p4.idx
        span13, span24 = t3 - t1, t4 - t2
        span12, span34 = t2 - t1, t4 - t3
        if span13 <= 2 or span24 <= 2 or span12 <= 1 or span34 <= 1:
            continue

        # Time symmetry of the wave: point 5 at t3 + (t3 − t1)
        t5 = t3 + span13
        if t5 <= t4:
            t5 = t4 + max(span34, span12 // 2, 4)
        t5 = min(t5, t4 + MAX_T5_BARS)

        ci = min(p4.confirmed_idx, n - 1)
        ar = atr_ratio[ci]
        if np.isfinite(ar) and ar > MAX_ATR_RATIO:
            continue

        impulse = abs(p2.price - p1.price)
        if impulse / max(p1.price, 1e-9) * 100.0 < MIN_IMPULSE_PCT:
            continue
        w34 = abs(p4.price - p3.price)
        if w34 <= 0:
            continue
        wr = impulse / w34
        if wr < MIN_WAVE_RATIO or wr > MAX_WAVE_RATIO:
            continue

        p5 = _line(t1, p1.price, t3, p3.price, t5)
        t_epa = min(t5 + max(span24, span13 // 2, 8), t5 + 80)
        epa = _line(t1, p1.price, t4, p4.price, t_epa)

        def width_at(t):
            return abs(
                _line(t1, p1.price, t3, p3.price, t) - _line(t2, p2.price, t4, p4.price, t)
            )

        w_early, w_late = width_at(t3), width_at(t4)
        if not (w_early > 0 and w_late < w_early * 0.97):
            continue  # channel must converge (true wedge)

        direction = "BUY" if p1.kind == "LOW" else "SELL"
        if direction == "BUY":
            # Falling wedge: 3 at/under 1, 4 under 2, 5 continues the 1–3 slope
            if p3.price > p1.price * 1.001 or p4.price >= p2.price:
                continue
            if p5 >= p4.price or p5 > p3.price * 1.002:
                continue
            move = (epa / p5 - 1.0) * 100.0
            bounce = (p2.price / p5 - 1.0) * 100.0
        else:
            if p3.price < p1.price * 0.999 or p4.price <= p2.price:
                continue
            if p5 <= p4.price or p5 < p3.price * 0.998:
                continue
            move = (1.0 - epa / p5) * 100.0
            bounce = (1.0 - p2.price / p5) * 100.0
        cands = [x for x in (move, bounce) if x > 0]
        room = min(cands) if cands else 0.0
        if room < MIN_MOVE_PCT or p5 <= 0:
            continue

        w = impulse * ZONE_HALF_RATIO
        a = atr[ci]
        if np.isfinite(a):
            w = max(w, 0.28 * a)
        w = min(max(w, p5 * 0.0010), p5 * 0.0050)

        conv = float(np.clip((w_early - w_late) / w_early, 0, 1))
        r12_34 = span34 / span12
        r13_35 = (t5 - t3) / span13 if span13 else 9.0
        tscore = 1.0 - min(abs(math.log(max(r12_34, 1e-6))), 1.0) * 0.5
        tscore *= 1.0 - min(abs(math.log(max(r13_35, 1e-6))), 1.0) * 0.5
        score = 0.38 * conv + 0.28 * tscore + 0.34 * float(np.clip(room / 1.2, 0, 1))
        out.append(
            Zone(
                direction, ci, ci, min(n - 1, max(t5, ci + 12), ci + FORWARD_BARS),
                p5 - w, p5 + w, p5, room, score,
            )
        )

    # Keep the higher-score zone when two same-direction boxes overlap
    ordered = sorted(out, key=lambda z: (-z.score, z.confirm_idx))
    kept: List[Zone] = []
    for z in ordered:
        clash = False
        for k in kept:
            if z.direction != k.direction:
                continue
            if abs(z.confirm_idx - k.confirm_idx) < OVERLAP_GAP:
                clash = True
                break
            if abs(z.z_mid - k.z_mid) / max(k.z_mid, 1e-9) * 100 < 0.15 and abs(
                z.confirm_idx - k.confirm_idx
            ) < 24:
                clash = True
                break
        if not clash:
            kept.append(z)
    kept.sort(key=lambda z: z.confirm_idx)
    return kept


def evaluate(df: pd.DataFrame, zones: List[Zone]) -> None:
    highs, lows, closes = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    n = len(df)
    touch = hit = 0
    mfes, maes = [], []
    for z in zones:
        i0, i1 = z.confirm_idx + 1, min(n, z.confirm_idx + 1 + FORWARD_BARS)
        touched = reached = False
        px = z.z_mid
        mfe = mae = 0.0
        for i in range(i0, i1):
            h, l, c = highs[i], lows[i], closes[i]
            if not touched:
                if h >= z.z_low and l <= z.z_high:
                    touched = True
                    px = (
                        min(max(l, z.z_low), z.z_high)
                        if z.direction == "BUY"
                        else max(min(h, z.z_high), z.z_low)
                    )
                elif (z.direction == "BUY" and c < z.z_low) or (
                    z.direction == "SELL" and c > z.z_high
                ):
                    break
                else:
                    continue
            if z.direction == "BUY":
                mfe = max(mfe, (h - px) / px * 100)
                mae = min(mae, (l - px) / px * 100)
                if mfe >= MIN_MOVE_PCT:
                    reached = True
                    break
                if c < z.z_low:
                    break
            else:
                mfe = max(mfe, (px - l) / px * 100)
                mae = min(mae, (px - h) / px * 100)
                if mfe >= MIN_MOVE_PCT:
                    reached = True
                    break
                if c > z.z_high:
                    break
        touch += int(touched)
        hit += int(reached)
        if touched:
            mfes.append(mfe)
            maes.append(mae)
    n_z = len(zones)
    print(f"zones {n_z}  buy {sum(z.direction=='BUY' for z in zones)}  sell {sum(z.direction=='SELL' for z in zones)}")
    print(
        f"touch {touch/n_z*100:.1f}%  hit|touch {hit/max(touch,1)*100:.1f}%  "
        f"≥0.4% of all boxes {hit/n_z*100:.1f}%"
    )
    if mfes:
        print(f"MFE {np.mean(mfes):+.3f}%  MAE {np.mean(maes):+.3f}%  payoff {abs(np.mean(mfes)/np.mean(maes)):.2f}x")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "scaner5_NVTK.xlsx"
    df = pd.read_excel(path)
    df = df.rename(
        columns={
            "DATE": "time",
            "candle_open": "open",
            "candle_high": "high",
            "candle_low": "low",
            "candle_close": "close",
            "candle_volume": "volume",
        }
    )
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    prev = df["close"].shift(1)
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum((df["high"] - prev).abs(), (df["low"] - prev).abs()),
    )
    df["atr"] = tr.rolling(14).mean()
    df["atr_med"] = df["atr"].rolling(50).median().shift(1)
    df["atr_ratio"] = df["atr"] / df["atr_med"]
    pivots = build_causal_zigzag(df)
    zones = wolfe_zones(df, pivots)
    evaluate(df, zones)
