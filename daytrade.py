# -*- coding: utf-8 -*-
"""
⚡ 當沖候選名單（收盤後挑「明天」的當沖觀察標的）
==================================================
跟 screener.py 的波段選股是兩套獨立邏輯。波段看的是「趨勢會不會延續好幾天」，
當沖只在乎「明天盤中有沒有足夠的價差、進出順不順、方向清不清楚」，所以條件完全不同：

硬性濾網（不符合直接不列入）：
  成交量 >= DT_MIN_VOLUME_LOTS、成交值 >= DT_MIN_TURNOVER、股價介於 DT_MIN_PRICE ~ DT_MAX_PRICE、
  排除 ETF（可關）、不在官方可當沖清單上的排除（有抓到清單時才套用）

6 個計分項目（權重可在 config.py 調整，總和100）：
  A 波動度  ATR% 落在 DT_ATR_PCT_MIN ~ DT_ATR_PCT_MAX（有價差可賺，又不會野到停損一直被掃）
  B 流動性  成交值越大越好（對數比例給分，大單進出不會滑價）
  C 量能    今日量 / 近5日均量 >= DT_VOLUME_RATIO_MIN（今天有人氣，明天大多還有人在玩）
  D 收盤    做多：收在當日高檔區；做空：收在當日低檔區（尾盤力道延續到隔天開盤）
  E 順勢    做多：收盤>5日線>10日線 或 突破20日高；做空：反之
  F 法人    做多：外資或投信買超；做空：外資或投信賣超

方向：今天收紅列入「偏多」、收黑列入「偏空」，C~F 都用同一個方向去評分，
      所以不會出現「收黑但被當成強勢多方」的情況。
      被官方註記「暫停先賣後買」的股票不會出現在偏空名單。

收在漲跌停附近的會扣 DT_LIMIT_PENALTY 分並加註提醒（明天常直接跳空，不好進場）。

另外每檔會附上明天的「參考價位」：今日高低點、樞紐點 Pivot/R1/S1、ATR 參考停損距離，
只是讓你盤前先把關鍵價位標好，不是進出場建議。

限制：這裡只有「日K」資料，看不到盤中分時、委買委賣、隔日開盤跳空，
      所以這份名單是「縮小盤前觀察範圍」用，真正進場還是要看明天開盤後的量價。
"""

import math

import db
from indicators import calc_ma, volume_avg, rolling_prior_high
from config import (
    MARKETS, BACKFILL_TRADING_DAYS, BREAKOUT_LOOKBACK,
    DT_MIN_VOLUME_LOTS, DT_MIN_TURNOVER, DT_MIN_PRICE, DT_MAX_PRICE, DT_EXCLUDE_ETF,
    DT_ATR_PERIOD, DT_ATR_PCT_MIN, DT_ATR_PCT_MAX,
    DT_TURNOVER_FULL_SCORE, DT_VOLUME_RATIO_MIN, DT_VOLUME_RATIO_FULL,
    DT_CLOSE_POS_STRONG, DT_LIMIT_PCT, DT_LIMIT_PENALTY,
    DT_WEIGHT_VOLATILITY, DT_WEIGHT_LIQUIDITY, DT_WEIGHT_VOLUME,
    DT_WEIGHT_CLOSE, DT_WEIGHT_TREND, DT_WEIGHT_CHIPS,
    DT_MIN_SCORE, DT_TOP_N, DT_STOP_ATR_MULT,
)

DT_MIN_HISTORY_DAYS = max(DT_ATR_PERIOD + 1, BREAKOUT_LOOKBACK + 1, 12)


def calc_atr(highs, lows, closes, period=DT_ATR_PERIOD):
    """平均真實波幅（Wilder's smoothing），回傳與輸入等長的 list，資料不足處為 None。"""
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    trs = [None]
    for i in range(1, n):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr = sum(trs[1:period + 1]) / period
    out[period] = atr
    for i in range(period + 1, n):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i] = atr
    return out


def _volatility_score(atr_pct):
    """ATR% 在理想區間內給滿分；低於下限依比例遞減；高於上限（太野）打六折。"""
    if atr_pct >= DT_ATR_PCT_MIN and atr_pct <= DT_ATR_PCT_MAX:
        return DT_WEIGHT_VOLATILITY
    if atr_pct < DT_ATR_PCT_MIN:
        return DT_WEIGHT_VOLATILITY * max(0.0, atr_pct / DT_ATR_PCT_MIN) ** 2
    return DT_WEIGHT_VOLATILITY * 0.6


def _liquidity_score(turnover):
    if turnover >= DT_TURNOVER_FULL_SCORE:
        return DT_WEIGHT_LIQUIDITY
    lo, hi = math.log10(DT_MIN_TURNOVER), math.log10(DT_TURNOVER_FULL_SCORE)
    frac = (math.log10(max(turnover, 1.0)) - lo) / (hi - lo) if hi > lo else 1.0
    # 剛好達到硬性門檻也給 40% 基本分（能通過門檻本身就代表流動性及格）
    return DT_WEIGHT_LIQUIDITY * (0.4 + 0.6 * max(0.0, min(1.0, frac)))


def _volume_score(ratio):
    if ratio >= DT_VOLUME_RATIO_FULL:
        return DT_WEIGHT_VOLUME
    if ratio <= 1.0:
        return 0.0
    return DT_WEIGHT_VOLUME * (ratio - 1.0) / (DT_VOLUME_RATIO_FULL - 1.0)


def evaluate_daytrade(market, code, name, target_date, daytrade_list=None):
    """daytrade_list: db.get_daytrade_list() 的結果；空 dict 或 None 代表「沒有清單」，不套用可當沖濾網。"""
    if DT_EXCLUDE_ETF and code.startswith("00"):
        return None
    if daytrade_list and code not in daytrade_list:
        return None  # 不在官方可當沖清單上

    price_hist = db.get_price_history(market, code, target_date, BACKFILL_TRADING_DAYS)
    if len(price_hist) < DT_MIN_HISTORY_DAYS or price_hist[-1][0] != target_date:
        return None

    highs = [r[2] for r in price_hist]
    lows = [r[3] for r in price_hist]
    closes = [r[4] for r in price_hist]
    volumes = [r[5] or 0.0 for r in price_hist]
    t = len(closes) - 1
    close_t, high_t, low_t, volume_t = closes[t], highs[t], lows[t], volumes[t]
    prev_close = closes[t - 1]

    # ---------------- 硬性濾網 ----------------
    if not (DT_MIN_PRICE <= close_t <= DT_MAX_PRICE):
        return None
    if volume_t / 1000.0 < DT_MIN_VOLUME_LOTS:
        return None
    turnover = volume_t * close_t  # 成交值(元)近似值：成交股數 x 收盤價
    if turnover < DT_MIN_TURNOVER:
        return None

    atr = calc_atr(highs, lows, closes)[t]
    if atr is None or close_t <= 0 or prev_close <= 0:
        return None
    atr_pct = atr / close_t * 100.0
    change_pct = (close_t - prev_close) / prev_close * 100.0

    side = "多" if change_pct >= 0 else "空"
    sell_first_suspended = bool(daytrade_list and daytrade_list[code][0])
    if side == "空" and sell_first_suspended:
        return None  # 不能先賣後買，偏空方向沒辦法做

    notes = []

    # ---------------- A 波動度 ----------------
    cond_a = DT_ATR_PCT_MIN <= atr_pct <= DT_ATR_PCT_MAX
    score_a = _volatility_score(atr_pct)
    if atr_pct > DT_ATR_PCT_MAX:
        notes.append(f"⚠️波動過大(ATR {atr_pct:.1f}%)，停損要放寬、部位要縮小")

    # ---------------- B 流動性 ----------------
    cond_b = True  # 能走到這裡代表已通過成交值門檻
    score_b = _liquidity_score(turnover)

    # ---------------- C 量能放大 ----------------
    vavg = volume_avg(volumes)[t]
    vol_ratio = volume_t / vavg if vavg else 0.0
    cond_c = vol_ratio >= DT_VOLUME_RATIO_MIN
    score_c = _volume_score(vol_ratio)
    if cond_c:
        notes.append(f"量能放大{vol_ratio:.1f}倍")

    # ---------------- D 收盤位置（與方向一致）----------------
    rng = high_t - low_t
    close_pos = (close_t - low_t) / rng if rng > 0 else 0.5
    strength = close_pos if side == "多" else 1.0 - close_pos
    cond_d = strength >= DT_CLOSE_POS_STRONG
    # 收在振幅中間(0.5)以下給0分，達到 DT_CLOSE_POS_STRONG 給滿分，中間線性
    score_d = DT_WEIGHT_CLOSE * max(0.0, min(1.0, (strength - 0.5) / max(DT_CLOSE_POS_STRONG - 0.5, 1e-9)))
    if cond_d:
        notes.append("收在最高附近，尾盤強" if side == "多" else "收在最低附近，尾盤弱")

    # ---------------- E 順勢 ----------------
    ma5_t = calc_ma(closes, 5)[t]
    ma10_t = calc_ma(closes, 10)[t]
    prior_high = rolling_prior_high(highs, BREAKOUT_LOOKBACK)[t]
    prior_low = min(lows[max(0, t - BREAKOUT_LOOKBACK):t])
    if side == "多":
        aligned = ma5_t is not None and ma10_t is not None and close_t > ma5_t > ma10_t
        broke = prior_high is not None and close_t > prior_high
    else:
        aligned = ma5_t is not None and ma10_t is not None and close_t < ma5_t < ma10_t
        broke = close_t < prior_low
    cond_e = aligned or broke
    score_e = DT_WEIGHT_TREND if cond_e else 0.0
    if broke:
        notes.append(f"{'突破' if side == '多' else '跌破'}近{BREAKOUT_LOOKBACK}日{'高' if side == '多' else '低'}點")
    elif aligned:
        notes.append("均線多頭排列" if side == "多" else "均線空頭排列")

    # ---------------- F 法人同向 ----------------
    insti = db.get_institutional_history(market, code, target_date, 1)
    cond_f = False
    if insti and insti[-1][0] == target_date:
        f_net, tr_net = insti[-1][1] or 0.0, insti[-1][2] or 0.0
        if side == "多":
            cond_f = f_net > 0 or tr_net > 0
        else:
            cond_f = f_net < 0 or tr_net < 0
    score_f = DT_WEIGHT_CHIPS if cond_f else 0.0
    if cond_f:
        notes.append("法人同步買超" if side == "多" else "法人同步賣超")

    # ---------------- 其他提醒 ----------------
    limit_penalty = 0.0
    if abs(change_pct) >= DT_LIMIT_PCT:
        limit_penalty = DT_LIMIT_PENALTY
        notes.append("⚠️收漲停附近，明天容易跳空開高，追價風險大" if side == "多"
                     else "⚠️收跌停附近，明天容易跳空開低，不宜追空")
    dt_ratio = None
    if daytrade_list and daytrade_list[code][1] and volume_t > 0:
        dt_ratio = daytrade_list[code][1] / volume_t * 100.0
        if dt_ratio >= 40:
            notes.append(f"當沖率{dt_ratio:.0f}%(當沖客很多，盤中容易急拉急殺)")

    score = score_a + score_b + score_c + score_d + score_e + score_f - limit_penalty
    score = max(0.0, min(100.0, score))

    # ---------------- 明天的參考價位 ----------------
    pivot = (high_t + low_t + close_t) / 3.0
    r1 = 2 * pivot - low_t
    s1 = 2 * pivot - high_t
    stop_dist = atr * DT_STOP_ATR_MULT

    return {
        "market": market,
        "code": code,
        "name": name,
        "date": target_date,
        "side": side,
        "close": close_t,
        "change_pct": change_pct,
        "volume_lots": round(volume_t / 1000.0),
        "turnover_e8": round(turnover / 1e8, 2),   # 成交值(億)
        "atr_pct": round(atr_pct, 2),
        "vol_ratio": round(vol_ratio, 2),
        "close_pos": round(close_pos, 2),
        "daytrade_ratio": round(dt_ratio, 1) if dt_ratio is not None else None,
        "condA_volatility": cond_a,
        "condB_liquidity": cond_b,
        "condC_volume": cond_c,
        "condD_close": cond_d,
        "condE_trend": cond_e,
        "condF_chips": cond_f,
        "checklist_count": sum([cond_a, cond_b, cond_c, cond_d, cond_e, cond_f]),
        "score": round(score, 1),
        "high": high_t,
        "low": low_t,
        "pivot": round(pivot, 2),
        "r1": round(r1, 2),
        "s1": round(s1, 2),
        "atr": round(atr, 2),
        "stop_dist": round(stop_dist, 2),
        "notes": "；".join(notes),
    }


def run_daytrade_screen(target_date, min_score=DT_MIN_SCORE, top_n=DT_TOP_N):
    """回傳 (results, scanned_count, list_applied)：
    results        分數 >= min_score 的候選股（多空合計，依分數高到低，最多 top_n 檔）
    scanned_count  通過硬性濾網、實際被評分的檔數
    list_applied   有沒有套用到官方可當沖清單濾網（抓不到清單時為 False）
    """
    results = []
    scanned_count = 0
    list_applied = False
    for market in MARKETS:
        dt_list = db.get_daytrade_list(market, target_date)
        list_applied = list_applied or bool(dt_list)
        for code, name in db.list_codes_with_price_on(market, target_date):
            try:
                r = evaluate_daytrade(market, code, name, target_date, dt_list)
            except Exception as e:  # noqa: BLE001
                print(f"  [警告] 當沖 {market} {code} 計算失敗，略過：{e}")
                continue
            if r is None:
                continue
            scanned_count += 1
            if r["score"] >= min_score:
                results.append(r)

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_n], scanned_count, list_applied
