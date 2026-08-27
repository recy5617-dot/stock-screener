# -*- coding: utf-8 -*-
"""技術指標計算：MA20、KD(9,3,3)、量能、突破。"""

from config import (
    MA_PERIOD, KD_RSV_PERIOD, KD_K_SMOOTH, KD_D_SMOOTH,
    BREAKOUT_LOOKBACK, VOLUME_AVG_DAYS,
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
