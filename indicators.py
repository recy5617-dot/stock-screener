# -*- coding: utf-8 -*-
"""技術指標計算：MA20、KD(9,3,3)、量能、突破、MACD、RSI、布林通道。"""

from config import (
    MA_PERIOD, KD_RSV_PERIOD, KD_K_SMOOTH, KD_D_SMOOTH,
    BREAKOUT_LOOKBACK, VOLUME_AVG_DAYS,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    RSI_PERIOD, BB_PERIOD, BB_STD,
)


def calc_ma(closes, period=MA_PERIOD):
    """回傳與 closes 等長的 list，前 period-1 筆為 None。"""
    out = [None] * len(closes)
    for i in range(len(closes)):
        if i + 1 >= period:
            window = closes[i + 1 - period: i + 1]
            out[i] = sum(window) / period
    return out


def calc_kd(highs, lows, closes, rsv_period=KD_RSV_PERIOD, k_smooth=KD_K_SMOOTH, d_smooth=KD_D_SMOOTH):
    """標準式 KD：RSV -> K = 前一日K*(k_smooth-1)/k_smooth + RSV*1/k_smooth，D 同理。
    起始 K=D=50。回傳 (K_list, D_list)，長度與輸入相同；資料不足 rsv_period 的位置為 None。
    """
    n = len(closes)
    k_list = [None] * n
    d_list = [None] * n
    prev_k, prev_d = 50.0, 50.0
    for i in range(n):
        if i + 1 < rsv_period:
            continue
        window_h = highs[i + 1 - rsv_period: i + 1]
        window_l = lows[i + 1 - rsv_period: i + 1]
        hh, ll = max(window_h), min(window_l)
        if hh == ll:
            rsv = 50.0
        else:
            rsv = (closes[i] - ll) / (hh - ll) * 100.0
        k = prev_k * (k_smooth - 1) / k_smooth + rsv * 1 / k_smooth
        d = prev_d * (d_smooth - 1) / d_smooth + k * 1 / d_smooth
        k_list[i] = k
        d_list[i] = d
        prev_k, prev_d = k, d
    return k_list, d_list


def volume_avg(volumes, days=VOLUME_AVG_DAYS):
    """回傳「不含當日」的近 N 日均量 list，等長，前面資料不足處為 None。"""
    n = len(volumes)
    out = [None] * n
    for i in range(n):
        if i - days < 0:
            continue
        window = volumes[i - days: i]
        out[i] = sum(window) / days
    return out


def rolling_prior_high(highs, lookback=BREAKOUT_LOOKBACK):
    """回傳「不含當日」的近 N 日最高價（前高/整理區參考），等長。"""
    n = len(highs)
    out = [None] * n
    for i in range(n):
        if i - lookback < 0:
            start = 0
        else:
            start = i - lookback
        window = highs[start:i]
        out[i] = max(window) if window else None
    return out


def calc_ema(values, period):
    """指數移動平均。前面資料不足 period 的位置為 None，第一個有效值用簡單平均起算。"""
    n = len(values)
    out = [None] * n
    k = 2.0 / (period + 1)
    prev = None
    for i in range(n):
        if i + 1 < period:
            continue
        if prev is None:
            prev = sum(values[i + 1 - period: i + 1]) / period
        else:
            prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def calc_macd(closes, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL):
    """回傳 (macd_line, signal_line, histogram)，皆與 closes 等長，資料不足處為 None。"""
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    n = len(closes)
    macd_line = [None] * n
    for i in range(n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]

    # signal 線是對 macd_line 的 EMA；macd_line 前面有 None，要先找到第一個有效值再開始算
    signal_line = [None] * n
    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), None)
    if first_valid is not None:
        sub = [v for v in macd_line[first_valid:] if v is not None]
        ema_of_macd = calc_ema(sub, signal)
        for offset, val in enumerate(ema_of_macd):
            signal_line[first_valid + offset] = val

    histogram = [None] * n
    for i in range(n):
        if macd_line[i] is not None and signal_line[i] is not None:
            histogram[i] = macd_line[i] - signal_line[i]

    return macd_line, signal_line, histogram


def calc_rsi(closes, period=RSI_PERIOD):
    """標準 RSI（Wilder's smoothing）。回傳與 closes 等長的 list，前面資料不足處為 None。"""
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out

    gains, losses = [], []
    for i in range(1, n):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    idx = period  # gains[period-1] 對應 closes[period]
    if avg_loss == 0:
        out[idx] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[idx] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        idx = i + 1
        if avg_loss == 0:
            out[idx] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[idx] = 100.0 - (100.0 / (1.0 + rs))
    return out


def calc_bollinger(closes, period=BB_PERIOD, num_std=BB_STD):
    """布林通道：回傳 (mid, upper, lower)，皆與 closes 等長，資料不足處為 None。"""
    n = len(closes)
    mid = [None] * n
    upper = [None] * n
    lower = [None] * n
    for i in range(n):
        if i + 1 < period:
            continue
        window = closes[i + 1 - period: i + 1]
        m = sum(window) / period
        variance = sum((x - m) ** 2 for x in window) / period
        sd = variance ** 0.5
        mid[i] = m
        upper[i] = m + num_std * sd
        lower[i] = m - num_std * sd
    return mid, upper, lower
