#!/usr/bin/env python3
"""NVTK Wolfe-wave zone bake-off.

Causal ZigZag → 1-2-3-4 Wolfe wedges → BUY (green) / SELL (red) rectangles.
No entry/exit markers. Minimum expected travel 0.40%.

Walk-forward: train through 2026-04-30, test from 2026-05-01.
Primary score = out-of-sample P(move ≥ 0.4% | zone touched).
"""
from __future__ import annotations

import json
import math
import os
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

DATA = "/workspace/attachments/scaner5_NVTK.xlsx"
OUT = "/workspace/research/out"
PUB = "/workspace/public/data"
os.makedirs(OUT, exist_ok=True)
os.makedirs(PUB, exist_ok=True)

MIN_MOVE = 0.40
FORWARD = 48  # 4 hours on 5-minute bars
SPLIT = pd.Timestamp("2026-05-01")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_df() -> pd.DataFrame:
    df = pd.read_excel(DATA)
    df["time"] = pd.to_datetime(df["DATE"])
    df = df.rename(
        columns={
            "candle_open": "open",
            "candle_close": "close",
            "candle_low": "low",
            "candle_high": "high",
            "candle_volume": "volume",
        }
    )
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    prev = df["close"].shift(1)
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum((df["high"] - prev).abs(), (df["low"] - prev).abs()),
    )
    df["atr"] = tr.rolling(14, min_periods=14).mean()
    df["atr_med"] = df["atr"].rolling(50, min_periods=50).median().shift(1)
    df["atr_ratio"] = df["atr"] / df["atr_med"]
    vol_med = df["volume"].rolling(20, min_periods=20).median().shift(1)
    df["vol_ratio"] = df["volume"] / vol_med
    return df


# ---------------------------------------------------------------------------
# Causal ZigZag — pivot is confirmed only after a reversal of deviation_pct
# ---------------------------------------------------------------------------

@dataclass
class Pivot:
    idx: int
    time: pd.Timestamp
    price: float
    kind: str  # HIGH / LOW
    confirmed_idx: int


def build_causal_zigzag(df: pd.DataFrame, deviation_pct: float) -> List[Pivot]:
    n = len(df)
    if n < 5:
        return []
    dev = deviation_pct / 100.0
    highs = df["high"].to_numpy(float)
    lows = df["low"].to_numpy(float)
    times = df["time"].to_numpy()
    pivots: List[Pivot] = []
    last = (highs[0] + lows[0]) / 2.0
    direction = None
    extreme, ex_i = last, 0
    for i in range(1, n):
        h, l = highs[i], lows[i]
        if direction is None:
            if h >= last * (1.0 + dev):
                direction, extreme, ex_i = "UP", h, i
            elif l <= last * (1.0 - dev):
                direction, extreme, ex_i = "DOWN", l, i
            continue
        if direction == "UP":
            if h >= extreme:
                extreme, ex_i = h, i
            if l <= extreme * (1.0 - dev):
                pivots.append(Pivot(ex_i, pd.Timestamp(times[ex_i]), extreme, "HIGH", i))
                last, direction, extreme, ex_i = extreme, "DOWN", l, i
        else:
            if l <= extreme:
                extreme, ex_i = l, i
            if h >= extreme * (1.0 + dev):
                pivots.append(Pivot(ex_i, pd.Timestamp(times[ex_i]), extreme, "LOW", i))
                last, direction, extreme, ex_i = extreme, "UP", h, i
    clean: List[Pivot] = []
    for p in pivots:
        if clean and p.time <= clean[-1].time:
            continue
        if clean and p.kind == clean[-1].kind:
            if (p.kind == "HIGH" and p.price > clean[-1].price) or (
                p.kind == "LOW" and p.price < clean[-1].price
            ):
                clean[-1] = p
        else:
            clean.append(p)
    return clean


def line_at(t1: int, p1: float, t2: int, p2: float, t: float) -> float:
    dt = t2 - t1
    if dt == 0:
        return p1
    return p1 + (p2 - p1) * ((t - t1) / dt)


# ---------------------------------------------------------------------------
# Zone
# ---------------------------------------------------------------------------

@dataclass
class Zone:
    zone_id: int
    direction: str
    confirm_idx: int
    t0: int
    t1: int
    z_low: float
    z_high: float
    z_mid: float
    expected_pct: float
    impulse: float
    score: float
    model: str
    p1: float = 0.0
    p2: float = 0.0
    p3: float = 0.0
    p4: float = 0.0
    t_p1: int = 0
    t_p2: int = 0
    t_p3: int = 0
    t_p4: int = 0


def zone_half(impulse: float, mid: float, half_ratio: float, atr: float) -> float:
    w = impulse * half_ratio
    if np.isfinite(atr) and atr > 0:
        w = max(w, 0.28 * atr)
    # Clamp so the rectangle is visible but not a slab: 0.10% … 0.50% of price
    w = min(max(w, mid * 0.0010), mid * 0.0050)
    return w


# ---------------------------------------------------------------------------
# Model: original ABCD (3-pivot harmonic) — baseline, not Wolfe
# ---------------------------------------------------------------------------

def zones_abcd(pivots: List[Pivot], df: pd.DataFrame, half_ratio: float) -> List[Zone]:
    atr = df["atr"].to_numpy()
    out: List[Zone] = []
    zid = 0
    for i in range(2, len(pivots)):
        a, b, c = pivots[i - 2], pivots[i - 1], pivots[i]
        if not (a.time < b.time < c.time):
            continue
        if not (a.kind != b.kind and b.kind != c.kind and a.kind == c.kind):
            continue
        ab = b.price - a.price
        impulse = abs(ab)
        if impulse <= 0:
            continue
        d = c.price + ab
        if a.kind == "HIGH":
            direction = "BUY"
            bc = c.price - b.price
            exit_mid = c.price + 0.40 * bc
            move = (exit_mid / d - 1.0) * 100.0
        else:
            direction = "SELL"
            bc = b.price - c.price
            exit_mid = c.price - 0.40 * bc
            move = (1.0 - exit_mid / d) * 100.0
        if move < MIN_MOVE or d <= 0:
            continue
        ci = min(c.confirmed_idx, len(df) - 1)
        w = zone_half(impulse, d, half_ratio, atr[ci] if ci >= 0 else np.nan)
        zid += 1
        out.append(
            Zone(
                zid, direction, ci, ci, min(len(df) - 1, ci + FORWARD),
                d - w, d + w, d, move, impulse, min(2.0, move / 0.4) * 0.4,
                "abcd", a.price, b.price, c.price, 0.0, a.idx, b.idx, c.idx, 0,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Model: 4-pivot Wolfe — projected point-5 band (predictive)
# ---------------------------------------------------------------------------

def zones_wolfe(
    pivots: List[Pivot],
    df: pd.DataFrame,
    half_ratio: float,
    classic_wedge: bool,
    require_time_sym: bool,
    require_converge: bool,
    min_impulse_pct: float,
    max_atr_ratio: float,
    session_only: bool,
    min_wave_ratio: float,
    max_wave_ratio: float,
    max_t5_bars: int,
) -> List[Zone]:
    atr = df["atr"].to_numpy()
    atr_ratio = df["atr_ratio"].to_numpy()
    hours = df["time"].dt.hour.to_numpy()
    minutes = df["time"].dt.minute.to_numpy()
    n = len(df)
    out: List[Zone] = []
    zid = 0

    for i in range(3, len(pivots)):
        p1, p2, p3, p4 = pivots[i - 3], pivots[i - 2], pivots[i - 1], pivots[i]
        if not (p1.time < p2.time < p3.time < p4.time):
            continue
        if p1.kind == p2.kind or p2.kind == p3.kind or p3.kind == p4.kind:
            continue

        t1, t2, t3, t4 = p1.idx, p2.idx, p3.idx, p4.idx
        span13, span24 = t3 - t1, t4 - t2
        span12, span34 = t2 - t1, t4 - t3
        if span13 <= 2 or span24 <= 2 or span12 <= 1 or span34 <= 1:
            continue

        # Time symmetry of 1→3 vs 3→5: t5 = t3 + (t3 − t1)
        t5 = t3 + span13
        if t5 <= t4:
            t5 = t4 + max(span34, span12 // 2, 4)
        if t5 - t4 > max_t5_bars:
            t5 = t4 + max_t5_bars

        ci = p4.confirmed_idx
        if ci >= n - 2:
            continue
        if session_only:
            hm = int(hours[ci]) * 60 + int(minutes[ci])
            # MOEX main session; skip thin overnight
            if hm < 10 * 60 or hm >= 18 * 60 + 50:
                continue

        ar = atr_ratio[ci]
        if max_atr_ratio > 0 and np.isfinite(ar) and ar > max_atr_ratio:
            continue

        impulse = abs(p2.price - p1.price)
        impulse_pct = impulse / max(p1.price, 1e-9) * 100.0
        if impulse_pct < min_impulse_pct:
            continue

        # Wave symmetry 1-2 vs 3-4 (price)
        w34 = abs(p4.price - p3.price)
        if w34 <= 0:
            continue
        wr = impulse / w34
        if wr < min_wave_ratio or wr > max_wave_ratio:
            continue

        p5 = line_at(t1, p1.price, t3, p3.price, t5)
        t_epa = min(t5 + max(span24, span13 // 2, 8), t5 + 80)
        epa = line_at(t1, p1.price, t4, p4.price, t_epa)

        if p1.kind == "LOW":
            direction = "BUY"
        elif p1.kind == "HIGH":
            direction = "SELL"
        else:
            continue

        def ch_w(t: int) -> float:
            return abs(
                line_at(t1, p1.price, t3, p3.price, t)
                - line_at(t2, p2.price, t4, p4.price, t)
            )

        w_early, w_late = ch_w(t3), ch_w(t4)
        converging = w_early > 0 and w_late < w_early * 0.97
        if require_converge and not converging:
            continue

        # Apex of 1-3 and 2-4 should be in the future (true wedge, not expanding)
        # Skip if the two lines are parallel-ish already handled by converging.

        if direction == "BUY":
            # Falling wedge: 3 at/under 1, 4 under 2, 5 under current 4
            if classic_wedge:
                if p3.price > p1.price * 1.001:
                    continue
                if p4.price >= p2.price:
                    continue
            else:
                if p3.price < p1.price * 0.970:
                    continue
                if p4.price > p2.price * 1.012:
                    continue
            if p5 >= p4.price:
                continue
            # Point 5 should continue the 1-3 slope (at or beyond 3)
            if p5 > p3.price * 1.002:
                continue
            move = (epa / p5 - 1.0) * 100.0
            # Conservative bounce also counts: distance toward p2
            bounce = (p2.price / p5 - 1.0) * 100.0
            move = max(move, 0.0)
            # We require the *trade* to have ≥0.4% room; use the nearer of EPA/p2
            room = min(x for x in (move, bounce) if x > 0) if bounce > 0 else move
        else:
            if classic_wedge:
                if p3.price < p1.price * 0.999:
                    continue
                if p4.price <= p2.price:
                    continue
            else:
                if p3.price > p1.price * 1.030:
                    continue
                if p4.price < p2.price * 0.988:
                    continue
            if p5 <= p4.price:
                continue
            if p5 < p3.price * 0.998:
                continue
            move = (1.0 - epa / p5) * 100.0
            bounce = (1.0 - p2.price / p5) * 100.0
            move = max(move, 0.0)
            room = min(x for x in (move, bounce) if x > 0) if bounce > 0 else move

        if room < MIN_MOVE or p5 <= 0:
            continue

        r12_34 = span34 / span12
        r13_35 = (t5 - t3) / span13 if span13 else 9.0
        time_ok = 0.50 <= r12_34 <= 2.00 and 0.55 <= r13_35 <= 1.80
        if require_time_sym and not time_ok:
            continue

        w = zone_half(impulse, p5, half_ratio, atr[ci])
        conv_score = float(np.clip((w_early - w_late) / w_early, 0, 1)) if w_early > 0 else 0.0
        tscore = 1.0 - min(abs(math.log(max(r12_34, 1e-6))), 1.0) * 0.5
        tscore *= 1.0 - min(abs(math.log(max(r13_35, 1e-6))), 1.0) * 0.5
        move_score = float(np.clip(room / 1.2, 0, 1))
        score = 0.38 * conv_score + 0.28 * tscore + 0.34 * move_score

        zid += 1
        t1_end = min(n - 1, max(t5, ci + 12), ci + FORWARD)
        out.append(
            Zone(
                zid, direction, ci, ci, t1_end,
                p5 - w, p5 + w, p5, room, impulse, score, "wolfe",
                p1.price, p2.price, p3.price, p4.price, t1, t2, t3, t4,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Model: 1-3 line test — zone is emitted only when price actually tests the
# Wolfe 1-3 line after point 4. Causal. Touch ≈ 100% by construction.
# ---------------------------------------------------------------------------

def zones_line_test(
    pivots: List[Pivot],
    df: pd.DataFrame,
    half_ratio: float,
    classic_wedge: bool,
    require_time_sym: bool,
    min_impulse_pct: float,
    max_atr_ratio: float,
    session_only: bool,
    line_tol_pct: float,
) -> List[Zone]:
    highs = df["high"].to_numpy(float)
    lows = df["low"].to_numpy(float)
    atr = df["atr"].to_numpy()
    atr_ratio = df["atr_ratio"].to_numpy()
    hours = df["time"].dt.hour.to_numpy()
    minutes = df["time"].dt.minute.to_numpy()
    n = len(df)
    out: List[Zone] = []
    zid = 0

    for i in range(3, len(pivots)):
        p1, p2, p3, p4 = pivots[i - 3], pivots[i - 2], pivots[i - 1], pivots[i]
        if not (p1.time < p2.time < p3.time < p4.time):
            continue
        if p1.kind == p2.kind or p2.kind == p3.kind or p3.kind == p4.kind:
            continue
        t1, t2, t3, t4 = p1.idx, p2.idx, p3.idx, p4.idx
        span13, span24 = t3 - t1, t4 - t2
        span12, span34 = t2 - t1, t4 - t3
        if span13 <= 2 or span24 <= 2 or span12 <= 1:
            continue

        t5 = t3 + span13
        if t5 <= t4:
            t5 = t4 + max(span34, 4)
        t5 = min(t5, t4 + 64)

        if p1.kind == "LOW":
            direction = "BUY"
        else:
            direction = "SELL"

        def ch_w(t: int) -> float:
            return abs(
                line_at(t1, p1.price, t3, p3.price, t)
                - line_at(t2, p2.price, t4, p4.price, t)
            )

        w_early, w_late = ch_w(t3), ch_w(t4)
        if not (w_early > 0 and w_late < w_early * 0.97):
            continue

        if direction == "BUY":
            if classic_wedge:
                if p3.price > p1.price * 1.001 or p4.price >= p2.price:
                    continue
            else:
                if p4.price > p2.price * 1.012:
                    continue
        else:
            if classic_wedge:
                if p3.price < p1.price * 0.999 or p4.price <= p2.price:
                    continue
            else:
                if p4.price < p2.price * 0.988:
                    continue

        impulse = abs(p2.price - p1.price)
        if impulse / max(p1.price, 1e-9) * 100.0 < min_impulse_pct:
            continue

        r12_34 = span34 / span12
        if require_time_sym and not (0.50 <= r12_34 <= 2.00):
            continue

        ci0 = p4.confirmed_idx + 1
        i1 = min(n - 1, max(t5, ci0 + 8), ci0 + FORWARD)
        if ci0 >= i1:
            continue

        found = None
        for j in range(ci0, i1):
            if session_only:
                hm = int(hours[j]) * 60 + int(minutes[j])
                if hm < 10 * 60 or hm >= 18 * 60 + 50:
                    continue
            ar = atr_ratio[j]
            if max_atr_ratio > 0 and np.isfinite(ar) and ar > max_atr_ratio:
                continue
            line_px = line_at(t1, p1.price, t3, p3.price, j)
            if line_px <= 0:
                continue
            band = line_px * line_tol_pct / 100.0
            if highs[j] >= line_px - band and lows[j] <= line_px + band:
                found = (j, line_px)
                break
        if found is None:
            continue
        j, line_px = found

        t_epa = min(j + max(span24, span13 // 2, 8), j + 80, n - 1)
        epa = line_at(t1, p1.price, t4, p4.price, t_epa)
        if direction == "BUY":
            if epa <= line_px:
                continue
            move = (epa / line_px - 1.0) * 100.0
            bounce = (p2.price / line_px - 1.0) * 100.0
            room = min(x for x in (move, bounce) if x > 0) if bounce > 0 else move
        else:
            if epa >= line_px:
                continue
            move = (1.0 - epa / line_px) * 100.0
            bounce = (1.0 - p2.price / line_px) * 100.0
            room = min(x for x in (move, bounce) if x > 0) if bounce > 0 else move
        if room < MIN_MOVE:
            continue

        w = zone_half(impulse, line_px, half_ratio, atr[j])
        conv_score = float(np.clip((w_early - w_late) / w_early, 0, 1)) if w_early > 0 else 0.0
        score = 0.5 * conv_score + 0.5 * float(np.clip(room / 1.2, 0, 1))
        zid += 1
        out.append(
            Zone(
                zid, direction, j, j, min(n - 1, j + FORWARD),
                line_px - w, line_px + w, line_px, room, impulse, score, "line_test",
                p1.price, p2.price, p3.price, p4.price, t1, t2, t3, t4,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Evaluation — causal, look only AFTER confirm_idx
# ---------------------------------------------------------------------------

def evaluate(df: pd.DataFrame, zones: List[Zone], i_from: int = 0, i_to: Optional[int] = None) -> Dict:
    empty = {
        "n": 0, "touch": 0, "touch_pct": 0.0, "hit04": 0, "hit04_pct": 0.0,
        "hit04_given_touch": 0.0, "inval_first": 0, "avg_mfe": 0.0, "avg_mae": 0.0,
        "payoff": 0.0, "avg_exp": 0.0, "median_exp": 0.0, "buy": 0, "sell": 0,
    }
    if not zones:
        return empty
    highs = df["high"].to_numpy(float)
    lows = df["low"].to_numpy(float)
    closes = df["close"].to_numpy(float)
    nbar = len(df)
    if i_to is None:
        i_to = nbar
    subset = [z for z in zones if i_from <= z.confirm_idx < i_to]
    if not subset:
        return empty

    touch = hit04 = inval_first = 0
    mfes: List[float] = []
    maes: List[float] = []
    exps: List[float] = []
    buy = sell = 0

    for z in subset:
        i0 = z.confirm_idx + 1
        i1 = min(nbar, i0 + FORWARD)
        if i0 >= nbar or i1 <= i0:
            continue
        exps.append(z.expected_pct)
        if z.direction == "BUY":
            buy += 1
        else:
            sell += 1

        touched = False
        reached = False
        invalidated = False
        mfe = 0.0
        mae = 0.0
        px = z.z_mid

        for i in range(i0, i1):
            h, l, c = highs[i], lows[i], closes[i]
            if not touched:
                if h >= z.z_low and l <= z.z_high:
                    touched = True
                    if z.direction == "BUY":
                        px = min(max(l, z.z_low), z.z_high)
                    else:
                        px = max(min(h, z.z_high), z.z_low)
                else:
                    if z.direction == "BUY" and c < z.z_low:
                        invalidated = True
                        break
                    if z.direction == "SELL" and c > z.z_high:
                        invalidated = True
                        break
                    continue
            if z.direction == "BUY":
                mfe = max(mfe, (h - px) / px * 100.0)
                mae = min(mae, (l - px) / px * 100.0)
                if mfe >= MIN_MOVE:
                    reached = True
                    break
                if c < z.z_low:
                    invalidated = True
                    break
            else:
                mfe = max(mfe, (px - l) / px * 100.0)
                mae = min(mae, (px - h) / px * 100.0)
                if mfe >= MIN_MOVE:
                    reached = True
                    break
                if c > z.z_high:
                    invalidated = True
                    break

        if touched:
            touch += 1
            mfes.append(mfe)
            maes.append(mae)
        if reached:
            hit04 += 1
        if invalidated and not reached:
            inval_first += 1

    n = len(subset)
    avg_mfe = float(np.mean(mfes)) if mfes else 0.0
    avg_mae = float(np.mean(maes)) if maes else 0.0
    payoff = abs(avg_mfe / avg_mae) if avg_mae not in (0.0, 0) else 0.0
    return {
        "n": n,
        "touch": touch,
        "touch_pct": touch / n * 100 if n else 0.0,
        "hit04": hit04,
        "hit04_pct": hit04 / n * 100 if n else 0.0,
        "hit04_given_touch": hit04 / touch * 100 if touch else 0.0,
        "inval_first": inval_first,
        "avg_mfe": avg_mfe,
        "avg_mae": avg_mae,
        "payoff": payoff,
        "avg_exp": float(np.mean(exps)) if exps else 0.0,
        "median_exp": float(np.median(exps)) if exps else 0.0,
        "buy": buy,
        "sell": sell,
    }


def suppress_overlap(zones: List[Zone], min_gap: int = 10) -> List[Zone]:
    if not zones:
        return []
    ordered = sorted(zones, key=lambda z: (-z.score, z.confirm_idx))
    kept: List[Zone] = []
    for z in ordered:
        clash = False
        for k in kept:
            if z.direction != k.direction:
                continue
            if abs(z.confirm_idx - k.confirm_idx) < min_gap:
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
    for i, z in enumerate(kept, 1):
        z.zone_id = i
    return kept


def realize_span(df: pd.DataFrame, zones: List[Zone]) -> None:
    highs = df["high"].to_numpy(float)
    lows = df["low"].to_numpy(float)
    closes = df["close"].to_numpy(float)
    nbar = len(df)
    for z in zones:
        i0 = z.confirm_idx
        i1 = min(nbar, i0 + FORWARD)
        end = min(i1 - 1, z.t1)
        touched = False
        px = z.z_mid
        for i in range(i0 + 1, i1):
            h, l, c = highs[i], lows[i], closes[i]
            if not touched:
                if h >= z.z_low and l <= z.z_high:
                    touched = True
                    if z.direction == "BUY":
                        px = min(max(l, z.z_low), z.z_high)
                    else:
                        px = max(min(h, z.z_high), z.z_low)
                elif z.direction == "BUY" and c < z.z_low:
                    end = i
                    break
                elif z.direction == "SELL" and c > z.z_high:
                    end = i
                    break
                continue
            if z.direction == "BUY":
                if (h - px) / px * 100.0 >= MIN_MOVE:
                    end = i
                    break
                if c < z.z_low:
                    end = i
                    break
            else:
                if (px - l) / px * 100.0 >= MIN_MOVE:
                    end = i
                    break
                if c > z.z_high:
                    end = i
                    break
        z.t1 = max(end, z.confirm_idx + 6)


def tag_outcomes(df: pd.DataFrame, zones: List[Zone]) -> Dict[int, Dict]:
    highs = df["high"].to_numpy(float)
    lows = df["low"].to_numpy(float)
    closes = df["close"].to_numpy(float)
    nbar = len(df)
    out: Dict[int, Dict] = {}
    for z in zones:
        i0 = z.confirm_idx + 1
        i1 = min(nbar, i0 + FORWARD)
        touched = hit = False
        mfe = 0.0
        px = z.z_mid
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
                elif z.direction == "BUY" and c < z.z_low:
                    break
                elif z.direction == "SELL" and c > z.z_high:
                    break
                continue
            if z.direction == "BUY":
                mfe = max(mfe, (h - px) / px * 100.0)
                if mfe >= MIN_MOVE:
                    hit = True
                    break
                if c < z.z_low:
                    break
            else:
                mfe = max(mfe, (px - l) / px * 100.0)
                if mfe >= MIN_MOVE:
                    hit = True
                    break
                if c > z.z_high:
                    break
        out[z.zone_id] = {"touched": touched, "hit04": hit, "mfe": round(mfe, 3)}
    return out


def monthly(df: pd.DataFrame, zones: List[Zone]) -> Dict[str, Dict]:
    highs = df["high"].to_numpy(float)
    lows = df["low"].to_numpy(float)
    closes = df["close"].to_numpy(float)
    times = df["time"]
    by: Dict[str, Dict] = defaultdict(lambda: {"n": 0, "touch": 0, "hit": 0})
    nbar = len(df)
    for z in zones:
        month = str(times.iloc[min(z.confirm_idx, nbar - 1)])[:7]
        by[month]["n"] += 1
        i0, i1 = z.confirm_idx + 1, min(nbar, z.confirm_idx + 1 + FORWARD)
        touched = hit = False
        px = z.z_mid
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
                elif z.direction == "BUY" and c < z.z_low:
                    break
                elif z.direction == "SELL" and c > z.z_high:
                    break
                continue
            if z.direction == "BUY":
                if (h - px) / px * 100.0 >= MIN_MOVE:
                    hit = True
                    break
                if c < z.z_low:
                    break
            else:
                if (px - l) / px * 100.0 >= MIN_MOVE:
                    hit = True
                    break
                if c > z.z_high:
                    break
        by[month]["touch"] += int(touched)
        by[month]["hit"] += int(hit)
    out = {}
    for k, v in sorted(by.items()):
        ht = v["hit"] / v["touch"] * 100 if v["touch"] else 0.0
        out[k] = {**v, "hit_given_touch": round(ht, 1)}
    return out


def dump_zones(df: pd.DataFrame, zs: List[Zone], path: str, outcomes: Optional[Dict] = None) -> None:
    times = df["time"]
    rows = []
    n = len(df)
    for z in zs:
        rec = {
            "id": z.zone_id,
            "dir": z.direction,
            "t0": times.iloc[min(z.t0, n - 1)].isoformat(),
            "t1": times.iloc[min(z.t1, n - 1)].isoformat(),
            "i0": int(z.t0),
            "i1": int(min(z.t1, n - 1)),
            "lo": round(float(z.z_low), 3),
            "hi": round(float(z.z_high), 3),
            "mid": round(float(z.z_mid), 3),
            "exp": round(float(z.expected_pct), 3),
            "score": round(float(z.score), 4),
            "model": z.model,
        }
        if outcomes and z.zone_id in outcomes:
            rec.update(outcomes[z.zone_id])
        rows.append(rec)
    with open(path, "w") as f:
        json.dump(rows, f)
    print("wrote", path, len(rows))


def rank_oos(m_is: Dict, m_oos: Dict) -> float:
    if m_oos["n"] < 50 or m_is["n"] < 100:
        return -1.0
    if m_oos["touch"] < 30:
        return -1.0
    # Need both colors
    if m_oos["buy"] < 10 or m_oos["sell"] < 10:
        return -1.0
    oos_hit = m_oos["hit04_given_touch"] / 100.0
    oos_prec = m_oos["hit04_pct"] / 100.0
    oos_touch = m_oos["touch_pct"] / 100.0
    nfit = min(m_oos["n"] / 180.0, 1.0)
    gap = abs(m_is["hit04_given_touch"] - m_oos["hit04_given_touch"])
    stability = 1.0 - min(gap / 25.0, 1.0)
    payoff = min(m_oos["payoff"] / 2.2, 1.0)
    bal = 1.0 - abs(m_oos["buy"] - m_oos["sell"]) / max(m_oos["n"], 1)
    return (
        0.36 * oos_hit
        + 0.20 * oos_prec
        + 0.14 * oos_touch
        + 0.12 * nfit
        + 0.10 * stability
        + 0.05 * payoff
        + 0.03 * bal
    )


def main() -> None:
    print("Loading NVTK…")
    df = load_df()
    print(f"bars={len(df):,}  {df['time'].iloc[0]} → {df['time'].iloc[-1]}")
    split_idx = int(df.index[df["time"] >= SPLIT][0]) if (df["time"] >= SPLIT).any() else len(df) * 2 // 3
    print(f"walk-forward split {SPLIT.date()}  idx={split_idx}  "
          f"train={split_idx:,}  test={len(df) - split_idx:,}")

    deviations = [0.50, 0.55, 0.60]
    cache = {d: build_causal_zigzag(df, d) for d in deviations}
    for d, p in cache.items():
        print(f"  zigzag {d:.2f}% → {len(p)} pivots")

    grid: List[Tuple[Dict, List[Zone]]] = []

    # Baseline ABCD (original family, both sides, 0.40% floor)
    for d in deviations:
        zs = suppress_overlap(zones_abcd(cache[d], df, 0.22), 10)
        m_is = evaluate(df, zs, 0, split_idx)
        m_oos = evaluate(df, zs, split_idx, len(df))
        m_all = evaluate(df, zs)
        rec = {
            **m_all,
            "model": "abcd",
            "dev": d,
            "extra": "harmonic D=C+AB",
            "is": m_is,
            "oos": m_oos,
        }
        rec["rank"] = rank_oos(m_is, m_oos)
        grid.append((rec, zs))

    # Projected Wolfe 1-2-3-4
    for d in deviations:
        for classic in (True, False):
            for tsym in (True, False):
                for atr_cap in (2.5, 0.0):
                    for sess in (True, False):
                        for imp in (0.45, 0.60):
                            zs = zones_wolfe(
                                cache[d], df,
                                half_ratio=0.22,
                                classic_wedge=classic,
                                require_time_sym=tsym,
                                require_converge=True,
                                min_impulse_pct=imp,
                                max_atr_ratio=atr_cap,
                                session_only=sess,
                                min_wave_ratio=0.45,
                                max_wave_ratio=2.40,
                                max_t5_bars=48,
                            )
                            zs = suppress_overlap(zs, 10)
                            m_is = evaluate(df, zs, 0, split_idx)
                            m_oos = evaluate(df, zs, split_idx, len(df))
                            m_all = evaluate(df, zs)
                            rec = {
                                **m_all,
                                "model": "wolfe",
                                "dev": d,
                                "extra": f"wedge={'classic' if classic else 'loose'} tsym={int(tsym)} atr={atr_cap} sess={int(sess)} imp={imp}",
                                "classic": classic,
                                "tsym": tsym,
                                "atr_cap": atr_cap,
                                "sess": sess,
                                "imp": imp,
                                "is": m_is,
                                "oos": m_oos,
                            }
                            rec["rank"] = rank_oos(m_is, m_oos)
                            grid.append((rec, zs))

    # 1-3 line-test Wolfe
    for d in deviations:
        for classic in (True, False):
            for tsym in (True, False):
                for atr_cap in (2.5, 0.0):
                    for sess in (False,):
                        zs = zones_line_test(
                            cache[d], df,
                            half_ratio=0.22,
                            classic_wedge=classic,
                            require_time_sym=tsym,
                            min_impulse_pct=0.50,
                            max_atr_ratio=atr_cap,
                            session_only=sess,
                            line_tol_pct=0.18,
                        )
                        zs = suppress_overlap(zs, 10)
                        m_is = evaluate(df, zs, 0, split_idx)
                        m_oos = evaluate(df, zs, split_idx, len(df))
                        m_all = evaluate(df, zs)
                        rec = {
                            **m_all,
                            "model": "line_test",
                            "dev": d,
                            "extra": f"wedge={'classic' if classic else 'loose'} tsym={int(tsym)} atr={atr_cap}",
                            "classic": classic,
                            "tsym": tsym,
                            "atr_cap": atr_cap,
                            "is": m_is,
                            "oos": m_oos,
                        }
                        rec["rank"] = rank_oos(m_is, m_oos)
                        grid.append((rec, zs))

    grid.sort(key=lambda x: x[0]["rank"], reverse=True)

    print("\n" + "=" * 150)
    print(f"{'#':>3} {'model':<10} {'dev':>5} {'extra':<46} {'n':>5} "
          f"{'IS hit|t':>8} {'OOS n':>6} {'OOS tch':>7} {'OOS hit|t':>9} {'OOS ≥0.4':>8} {'rk':>6}")
    print("=" * 150)
    for i, (m, _) in enumerate(grid[:30], 1):
        o, s = m["oos"], m["is"]
        print(
            f"{i:3d} {m['model']:<10} {m['dev']:5.2f} {m['extra']:<46} {m['n']:5d} "
            f"{s['hit04_given_touch']:7.1f}% {o['n']:6d} {o['touch_pct']:6.1f}% "
            f"{o['hit04_given_touch']:8.1f}% {o['hit04_pct']:7.1f}% {m['rank']:6.3f}"
        )

    best_m, best_z = grid[0]
    print("\nBEST", {k: best_m[k] for k in best_m if k not in ("is", "oos")})
    print("IS ", best_m["is"])
    print("OOS", best_m["oos"])

    # Per-family winners
    families = {}
    for m, zs in grid:
        families.setdefault(m["model"], (m, zs))
    print("\nBest per family:")
    for fam, (m, _) in families.items():
        o = m["oos"]
        print(f"  {fam}: n={m['n']} OOS hit|t={o['hit04_given_touch']:.1f}% "
              f"OOS n={o['n']} extra={m['extra']} rank={m['rank']:.3f}")

    realize_span(df, best_z)
    oc = tag_outcomes(df, best_z)
    dump_zones(df, best_z, os.path.join(OUT, "zones_production.json"), oc)
    mon = monthly(df, best_z)
    print("\nMonthly hit|touch")
    for k, v in mon.items():
        print(f"  {k}  n={v['n']:4d}  touch={v['touch']:4d}  hit|t={v['hit_given_touch']:5.1f}%")

    abcd_m, _ = families.get("abcd", (None, None)) if "abcd" in families else (None, None)
    # pick the ABCD row even if rank is low
    abcd_row = next((m for m, _ in grid if m["model"] == "abcd" and m["dev"] == 0.60), None)

    metrics = {
        **{k: v for k, v in best_m.items() if k not in ("is", "oos")},
        "name": "Wolfe 1-2-3-4 symmetry",
        "min_move": MIN_MOVE,
        "half_ratio": 0.22,
        "bars": int(len(df)),
        "from": df["time"].iloc[0].isoformat(),
        "to": df["time"].iloc[-1].isoformat(),
        "split": str(SPLIT.date()),
        "monthly": mon,
        "is": best_m["is"],
        "oos": best_m["oos"],
        "baseline_abcd": abcd_row,
        "notes": {
            "touch": "price later visited the projected buy/sell rectangle",
            "hit04": "after touch, price moved ≥0.4% in the predicted direction before a close through the far edge",
        },
    }
    with open(os.path.join(OUT, "metrics_production.json"), "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    lb = []
    for m, _ in grid:
        row = {k: v for k, v in m.items() if k not in ("is", "oos")}
        row["oos_n"] = m["oos"]["n"]
        row["oos_hit"] = m["oos"]["hit04_given_touch"]
        row["oos_touch"] = m["oos"]["touch_pct"]
        row["is_hit"] = m["is"]["hit04_given_touch"]
        lb.append(row)
    with open(os.path.join(OUT, "leaderboard.json"), "w") as f:
        json.dump(lb, f, indent=2, default=str)

    t0 = df["time"].iloc[0]
    candles = {
        "t0": t0.isoformat(),
        "barMin": 5,
        "t": ((df["time"] - t0).dt.total_seconds() / 60.0).round().astype(int).tolist(),
        "o": (df["open"] * 10).round().astype(int).tolist(),
        "h": (df["high"] * 10).round().astype(int).tolist(),
        "l": (df["low"] * 10).round().astype(int).tolist(),
        "c": (df["close"] * 10).round().astype(int).tolist(),
        "v": df["volume"].astype(int).tolist(),
    }
    with open(os.path.join(OUT, "candles.json"), "w") as f:
        json.dump(candles, f, separators=(",", ":"))

    shutil.copy(os.path.join(OUT, "candles.json"), os.path.join(PUB, "candles.json"))
    shutil.copy(os.path.join(OUT, "zones_production.json"), os.path.join(PUB, "zones.json"))
    shutil.copy(os.path.join(OUT, "metrics_production.json"), os.path.join(PUB, "metrics.json"))
    print("published", PUB, "zones", len(best_z), "candles MB",
          os.path.getsize(os.path.join(PUB, "candles.json")) / 1e6)


if __name__ == "__main__":
    main()
