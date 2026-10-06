# -*- coding: utf-8 -*-
"""
個股短線分析（給「我的關注」頁用）
==================================
用每天收盤後的日K、三大法人、融資資料，對每檔股票算出一張固定格式的分析表：

  最新股價、短線趨勢、籌碼、量價、
  第一支撐、第二支撐、強支撐、第一壓力、第二壓力、
  建議買點、第二買點、不宜追價、短線停損、最終防守、
  第一停利、第二停利、波段目標、風險報酬比、操作建議

做法（全部是機械化規則，不是投資建議）：
  - 趨勢：收盤與 5/10/20 日線的排列，加上月線方向
  - 籌碼：近 5 日外資+投信買賣超、融資增減，跟近 5 日股價方向對照（例如價漲但法人賣、融資增 → 價強籌碼弱）
  - 量價：今日量 / 近 5 日均量，搭配今天漲跌
  - 支撐 / 壓力：把均線（5/10/20/60）、近 5/10/20/60 日高低點、樞紐點等候選價位，
    相近（1.5% 內）的合併成「區間」，由近到遠排出第一、第二、第三道；不夠的用 ATR 推估
  - 買點在第一支撐附近、停損在第二支撐下方、最終防守在強支撐下緣、停利在壓力，風險報酬比 =（第二停利 − 買點）÷（買點 − 停損）
"""

from indicators import calc_ma
from daytrade import calc_atr

# 標籤（網頁上只存代碼，標籤表內嵌一次；顏色 g=綠 y=黃 o=橘 r=紅 n=灰）
TRENDS = [("偏多", "g"), ("偏空", "r"), ("盤整偏多", "y"), ("盤整偏弱", "y")]
CHIPS = [("籌碼同步偏多", "g"), ("價強籌碼弱", "o"), ("價弱籌碼穩", "y"), ("籌碼偏空", "r"), ("資料不足", "n")]
VOLPRICE = [("強", "g"), ("偏強", "g"), ("價漲量縮", "y"), ("弱（價跌量增）", "r"), ("量縮回檔", "y"), ("中性", "y")]
ADVICE = ["等待回測、分批買", "回到買點附近，可分批布局", "區間操作：靠支撐買、近壓力賣",
          "風險報酬比偏低，等更好的買點", "趨勢偏空，先觀望不接刀", "已跌破停損，先出場觀望"]
WEAK_CHIPS_NOTE = "（籌碼偏弱，部位宜小）"
LABELS = {"t": TRENDS, "c": CHIPS, "v": VOLPRICE, "a": ADVICE, "w": WEAK_CHIPS_NOTE}

ZONE_MERGE_PCT = 0.015     # 候選價位相差 1.5% 內合併成同一個區間
MIN_GAP_PCT = 0.005        # 離收盤 0.5% 內的價位不算支撐/壓力（太近沒意義）
MIN_HISTORY = 25


def tick_size(price):
    """台股升降單位。"""
    if price < 10:
        return 0.01
    if price < 50:
        return 0.05
    if price < 100:
        return 0.1
    if price < 500:
        return 0.5
    if price < 1000:
        return 1.0
    return 5.0


def round_tick(price):
    t = tick_size(price)
    return round(round(price / t) * t, 2)


def floor_tick(price):
    t = tick_size(price)
    import math
    return round(math.floor(price / t + 1e-9) * t, 2)


def fmt(price):
    p = round_tick(price)
    return f"{p:.2f}".rstrip("0").rstrip(".")


def fmt_zone(lo, hi):
    lo, hi = round_tick(min(lo, hi)), round_tick(max(lo, hi))
    if hi - lo < tick_size(hi) * 0.5:
        return fmt(hi)
    return f"{fmt(lo)}～{fmt(hi)}"


def _zones(levels, descending):
    """把候選價位合併成區間 [(lo, hi), ...]；descending=True 給支撐（由近到遠往下），False 給壓力。"""
    levels = sorted(set(levels), reverse=descending)
    zones = []
    firsts = []
    for lv in levels:
        if zones and abs(lv - firsts[-1]) / firsts[-1] <= ZONE_MERGE_PCT:
            lo, hi = zones[-1]
            zones[-1] = (min(lo, lv), max(hi, lv))
            continue
        zones.append((lv, lv))
        firsts.append(lv)
    return zones


def _separate(zones, min_gap, descending):
    """相鄰兩個區間距離小於 min_gap 就併成一個，避免第一、第二道擠在一起（四捨五入到升降單位後會重疊）。"""
    out = []
    for z in zones:
        if out:
            lo, hi = out[-1]
            gap = (lo - z[1]) if descending else (z[0] - hi)
            if gap < min_gap:
                out[-1] = (min(lo, z[0]), max(hi, z[1]))
                continue
        out.append(z)
    return out


def analyze(price_hist, insti_hist=None, margin_hist=None):
    """price_hist: [(date, open, high, low, close, volume, change), ...] 由舊到新。
    insti_hist: [(date, foreign_net, trust_net, dealer_net, total_net), ...]
    margin_hist: [(date, margin_balance, margin_buy, margin_sell), ...]
    回傳 dict（欄位見檔頭），資料不足回傳 None。"""
    if len(price_hist) < MIN_HISTORY:
        return None
    highs = [r[2] for r in price_hist]
    lows = [r[3] for r in price_hist]
    closes = [r[4] for r in price_hist]
    volumes = [r[5] or 0.0 for r in price_hist]
    t = len(closes) - 1
    close = closes[t]
    if not close or close <= 0:
        return None

    atr = calc_atr(highs, lows, closes)[t] or (max(highs[-14:]) - min(lows[-14:])) / 4 or close * 0.02
    ma = {n: calc_ma(closes, n)[t] for n in (5, 10, 20, 60) if len(closes) >= n}
    ma20_prev = calc_ma(closes, 20)[t - 5]

    # ---------------- 短線趨勢 ----------------
    ma5, ma10, ma20 = ma.get(5), ma.get(10), ma.get(20)
    ma20_up = ma20_prev is not None and ma20 >= ma20_prev
    if close > ma20 and ma5 > ma10 and ma20_up:
        trend = 0
    elif close < ma20 and ma5 < ma10 and not ma20_up:
        trend = 1
    elif close > ma20:
        trend = 2
    else:
        trend = 3

    # ---------------- 籌碼 ----------------
    price_5d = close / closes[t - 5] - 1 if closes[t - 5] else 0.0
    dates5 = {r[0] for r in price_hist[-5:]}
    insti5 = [r for r in (insti_hist or []) if r[0] in dates5]
    margins = [r for r in (margin_hist or []) if r[1] is not None]
    if not insti5:
        chips = 4
    else:
        inst_net = sum((r[1] or 0) + (r[2] or 0) for r in insti5)
        margin_up = False
        if len(margins) >= 6 and margins[-6][1]:
            margin_up = (margins[-1][1] - margins[-6][1]) / margins[-6][1] > 0.03
        if price_5d > 0:
            chips = 0 if inst_net > 0 and not margin_up else 1
        else:
            chips = 2 if inst_net > 0 else 3

    # ---------------- 量價 ----------------
    vavg = sum(volumes[t - 5:t]) / 5 if t >= 5 else 0
    ratio = volumes[t] / vavg if vavg else 1.0
    up = closes[t] >= closes[t - 1]
    if up:
        vp = 0 if ratio >= 1.2 else 2 if ratio < 0.8 else 1
    else:
        vp = 3 if ratio >= 1.2 else 4 if ratio < 0.8 else 5

    # ---------------- 支撐 / 壓力 ----------------
    def hi_n(n):
        return max(highs[-n:]) if len(highs) >= n else None

    def lo_n(n):
        return min(lows[-n:]) if len(lows) >= n else None

    h, l = highs[t], lows[t]
    pivot = (h + l + close) / 3
    cands = [v for v in list(ma.values()) + [lo_n(5), lo_n(10), lo_n(20), lo_n(60), hi_n(5), hi_n(10),
                                               hi_n(20), hi_n(60), 2 * pivot - h, pivot - (h - l),
                                               2 * pivot - l, pivot + (h - l)] if v]
    sup = _zones([v for v in cands if v < close * (1 - MIN_GAP_PCT)], descending=True)
    res = _zones([v for v in cands if v > close * (1 + MIN_GAP_PCT)], descending=False)
    min_gap = max(atr * 0.4, tick_size(close) * 3)
    sup = _separate(sup, min_gap, descending=True)
    res = _separate(res, min_gap, descending=False)
    est_res = not res  # 創新高、上面沒有任何價位
    # 不夠三道就用 ATR 往外推（並保持由近到遠）
    step = max(atr, min_gap * 1.5)  # 波動極小的債券 ETF / 特別股，ATR 不到一檔，至少隔幾檔
    while len(sup) < 3:
        base = sup[-1][0] if sup else close
        lv = base - step
        sup.append((lv, lv))
    while len(res) < 3:
        base = res[-1][1] if res else close
        lv = base + step * (1.0 if len(res) < 2 else 1.5)
        res.append((lv, lv))
    s1, s2, s3 = sup[0], sup[1], sup[2]
    r1, r2, r3 = res[0], res[1], res[2]

    # ---------------- 買點 / 停損 / 停利 ----------------
    pad = atr * 0.25
    gap12 = s1[0] - s2[1]
    buy1 = (max(s1[0] - pad, s2[1] + gap12 / 2), min(s1[1] + pad, close))  # 不跟第二買點重疊
    buy2 = s2
    # 停損、最終防守一律「往下」取升降單位，四捨五入後才不會跟買點/停損黏在一起
    stop = floor_tick(min(s2[0] - atr * 0.3, s2[0] - tick_size(s2[0]) * 1.5))
    defend_hi = floor_tick(min(s3[0], stop - tick_size(stop)))  # 最終防守一定在短線停損之下
    defend = (defend_hi - atr * 0.3, defend_hi)
    chase_from = min(close + atr * 0.15, r1[0])
    # 網頁顯示時會接「元以上」
    nochase = f"{fmt(chase_from)}～{fmt(r1[0])}" if round_tick(chase_from) < round_tick(r1[0]) else fmt(r1[0])
    target = r3 if r3[0] > r2[1] + tick_size(r2[1]) else (r2[1] + step, r2[1] + step * 1.5)

    buy_mid = (buy1[0] + buy1[1]) / 2
    tp2_mid = (r2[0] + r2[1]) / 2
    risk = buy_mid - stop
    rr = (tp2_mid - buy_mid) / risk if risk > 0 else None

    # ---------------- 操作建議 ----------------
    in_buy_zone = buy1[0] <= close <= buy1[1] + tick_size(close)
    if close < stop:
        advice = 5
    elif trend == 1:
        advice = 4
    elif rr is not None and rr < 1.5:
        advice = 3
    elif trend in (2, 3):
        advice = 2
    elif in_buy_zone:
        advice = 1
    else:
        advice = 0
    weak = chips in (1, 3) and advice not in (4, 5)

    return {
        "price": fmt(close),
        "trend": trend, "chips": chips, "vp": vp,
        "s1": fmt_zone(*s1), "s2": fmt_zone(*s2), "s3": fmt_zone(*s3),
        "r1": fmt_zone(*r1), "r2": fmt_zone(*r2),
        "buy1": fmt_zone(*buy1), "buy2": fmt_zone(*buy2),
        "nochase": nochase,
        "stop": fmt(stop), "defend": fmt_zone(*defend),
        "tp1": fmt_zone(*r1), "tp2": fmt_zone(*r2), "target": fmt_zone(*target),
        "rr": f"1：{rr:.1f}" if rr is not None and rr > 0 else "—",
        "advice": advice, "weak": weak,
        "est": est_res,
    }


def labels_of(a):
    """把代碼換回文字，給 Python 端（測試、命令列）看。"""
    return {
        "trend": TRENDS[a["trend"]][0], "chips": CHIPS[a["chips"]][0], "vp": VOLPRICE[a["vp"]][0],
        "advice": ADVICE[a["advice"]] + (WEAK_CHIPS_NOTE if a["weak"] else ""),
    }


def to_compact(a):
    """內嵌到網頁用的精簡陣列（欄位順序要跟 docs/watchlist.js 的 ANALYSIS_ROWS 一致）。"""
    # 第一/第二停利就是第一/第二壓力，網頁端直接沿用，不重複存
    return [a["price"], a["trend"], a["chips"], a["vp"], a["s1"], a["s2"], a["s3"], a["r1"], a["r2"],
            a["buy1"], a["buy2"], a["nochase"], a["stop"], a["defend"], a["target"], a["rr"],
            a["advice"], 1 if a["weak"] else 0, 1 if a["est"] else 0]


def analyze_all(market, target_date, codes):
    """對 codes 每一檔做分析，回傳 {code: compact_list}。"""
    import db
    from config import BACKFILL_TRADING_DAYS
    out = {}
    for code in codes:
        try:
            ph = db.get_price_history(market, code, target_date, BACKFILL_TRADING_DAYS)
            if not ph or ph[-1][0] != target_date:
                continue
            a = analyze(ph, db.get_institutional_history(market, code, target_date, 10),
                        db.get_margin_history(market, code, target_date, 10))
            if a:
                out[code] = to_compact(a)
        except Exception as e:  # noqa: BLE001
            print(f"  [警告] 分析 {code} 失敗，略過：{e}")
    return out
