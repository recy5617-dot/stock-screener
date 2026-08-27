# -*- coding: utf-8 -*-
"""
核心選股邏輯：「KD打勾＋月線上＋籌碼轉強」5 條件 + 加權評分
================================================================
5 條件（達成數，對應你原本的打分表）：
  ① 股價站上 20 日月線
  ② KD 向上打勾（K 由下往上轉，最漂亮是 K 上穿 D）
  ③ 法人籌碼轉強（外資由賣轉買 / 投信連買 / 三大法人合計由賣轉買，任一即算）
  ④ 融資沒有暴增（股價漲＋融資也暴增 -> 不算過關；融資持平或下降更漂亮）
  ⑤ 突破或轉強有量（帶量突破前高/整理區，且收盤不是長上影線）

加權分數（0~100，用來在同一級距內排序）依你的權重順序：
  月線方向(35) ＞ 籌碼(30) ＞ 成交量(20) ＞ KD(15)；融資是風險濾網，暴增倒扣分數。
"""

from indicators import calc_ma, calc_kd, volume_avg, rolling_prior_high
import db
from config import (
    MA_PERIOD, MA_SLOPE_LOOKBACK, MA_JUST_RECLAIMED_LOOKBACK,
    KD_HIGH_ZONE, KD_STAGNANT_DAYS, TRUST_CONSEC_BUY_DAYS,
    MARGIN_SURGE_THRESHOLD, BREAKOUT_LOOKBACK, VOLUME_SURGE_RATIO,
    LONG_UPPER_SHADOW_RATIO, WEIGHT_MA20, WEIGHT_CHIPS, WEIGHT_VOLUME,
    WEIGHT_KD, MARGIN_PENALTY_POINTS, BACKFILL_TRADING_DAYS,
)

MIN_HISTORY_DAYS = max(MA_PERIOD + MA_SLOPE_LOOKBACK, BREAKOUT_LOOKBACK + 5, 30)


def _align_by_date(price_hist, insti_hist, margin_hist):
    """三份歷史資料日期不一定完全對齊（法人/融資偶爾缺值），用價格的日期為主軸，
    其餘資料找不到當天就視為 0（保守處理，不會誤判成轉強）。"""
    insti_map = {r[0]: r for r in insti_hist}
    margin_map = {r[0]: r for r in margin_hist}

    dates = [r[0] for r in price_hist]
    foreign_net = []
    trust_net = []
    total_net = []
    margin_balance = []
    for d in dates:
        ir = insti_map.get(d)
        foreign_net.append(ir[1] if ir else 0.0)
        trust_net.append(ir[2] if ir else 0.0)
        total_net.append(ir[4] if ir else 0.0)
        mr = margin_map.get(d)
        margin_balance.append(mr[1] if mr else None)
    return foreign_net, trust_net, total_net, margin_balance


def evaluate_stock(market: str, code: str, name: str, target_date: str):
    price_hist = db.get_price_history(market, code, target_date, BACKFILL_TRADING_DAYS)
    if len(price_hist) < MIN_HISTORY_DAYS:
        return None
    if price_hist[-1][0] != target_date:
        return None  # 當天沒有成交資料（可能停牌）

    insti_hist = db.get_institutional_history(market, code, target_date, BACKFILL_TRADING_DAYS)
    margin_hist = db.get_margin_history(market, code, target_date, BACKFILL_TRADING_DAYS)

    dates = [r[0] for r in price_hist]
    opens = [r[1] for r in price_hist]
    highs = [r[2] for r in price_hist]
    lows = [r[3] for r in price_hist]
    closes = [r[4] for r in price_hist]
    volumes = [r[5] for r in price_hist]
    changes = [r[6] for r in price_hist]

    ma20 = calc_ma(closes, MA_PERIOD)
    k_list, d_list = calc_kd(highs, lows, closes)
    vavg = volume_avg(volumes)
    prior_high = rolling_prior_high(highs, BREAKOUT_LOOKBACK)

    foreign_net, trust_net, total_net, margin_balance = _align_by_date(price_hist, insti_hist, margin_hist)

    t = len(closes) - 1  # 今日索引
    close_t = closes[t]
    high_t, low_t = highs[t], lows[t]
    volume_t = volumes[t]

    notes = []

    # ---------------- ① 月線 ----------------
    ma_t = ma20[t]
    ma_t5 = ma20[t - MA_SLOPE_LOOKBACK] if t - MA_SLOPE_LOOKBACK >= 0 else None
    cond1_pass = ma_t is not None and close_t > ma_t
    ma_rising = ma_t is not None and ma_t5 is not None and ma_t >= ma_t5
    just_reclaimed = False
    if cond1_pass:
        for j in range(max(0, t - MA_JUST_RECLAIMED_LOOKBACK), t):
            if ma20[j] is not None and closes[j] <= ma20[j]:
                just_reclaimed = True
                break

    if cond1_pass and ma_rising:
        ma_score = WEIGHT_MA20
        notes.append("站穩月線且月線向上")
    elif cond1_pass and just_reclaimed:
        ma_score = WEIGHT_MA20 * 0.6
        notes.append("剛站回月線(觀察)")
    elif cond1_pass:
        ma_score = WEIGHT_MA20 * 0.8
        notes.append("站上月線")
    else:
        ma_score = 0.0

    # ---------------- ② KD ----------------
    k_t, d_t = k_list[t], d_list[t]
    k_p1 = k_list[t - 1] if t - 1 >= 0 else None
    k_p2 = k_list[t - 2] if t - 2 >= 0 else None
    d_p1 = d_list[t - 1] if t - 1 >= 0 else None

    turning_up = (k_t is not None and k_p1 is not None and k_t > k_p1
                  and (k_p2 is None or k_p1 <= k_p2))
    golden_cross = (k_t is not None and d_t is not None and k_p1 is not None and d_p1 is not None
                     and k_p1 <= d_p1 and k_t > d_t)
    cond2_pass = bool(turning_up or golden_cross)

    stagnant_high = False
    if k_t is not None:
        window = [v for v in k_list[max(0, t - KD_STAGNANT_DAYS + 1): t + 1] if v is not None]
        stagnant_high = len(window) >= KD_STAGNANT_DAYS and all(v > KD_HIGH_ZONE for v in window)

    if cond2_pass and golden_cross and not stagnant_high:
        kd_score = WEIGHT_KD
        notes.append("K上穿D golden cross")
    elif cond2_pass and not stagnant_high:
        kd_score = WEIGHT_KD * 0.7
        notes.append("K由下往上轉")
    elif cond2_pass and stagnant_high:
        kd_score = WEIGHT_KD * 0.3
        notes.append("⚠️高檔鈍化已久，KD打勾勿單純追價")
    else:
        kd_score = 0.0

    # 月線下的 KD 打勾，優先級降低
    if not cond1_pass:
        kd_score *= 0.4

    # ---------------- ③ 籌碼 ----------------
    f_t, f_p1 = foreign_net[t], foreign_net[t - 1] if t - 1 >= 0 else None
    tot_t, tot_p1 = total_net[t], total_net[t - 1] if t - 1 >= 0 else None
    foreign_flip = f_p1 is not None and f_p1 < 0 and f_t > 0
    total_flip = tot_p1 is not None and tot_p1 < 0 and tot_t > 0
    trust_window = trust_net[max(0, t - TRUST_CONSEC_BUY_DAYS + 1): t + 1]
    trust_consec = len(trust_window) >= TRUST_CONSEC_BUY_DAYS and all(v > 0 for v in trust_window)

    triggers = sum([foreign_flip, trust_consec, total_flip])
    cond3_pass = triggers > 0
    if triggers == 0:
        chips_score = 0.0
    elif triggers == 1:
        chips_score = WEIGHT_CHIPS * 0.7
    elif triggers == 2:
        chips_score = WEIGHT_CHIPS * 0.9
    else:
        chips_score = WEIGHT_CHIPS

    if foreign_flip:
        notes.append("外資由賣轉買")
    if trust_consec:
        notes.append(f"投信連買{TRUST_CONSEC_BUY_DAYS}日+")
    if total_flip:
        notes.append("三大法人合計由賣轉買")

    # ---------------- ④ 融資 ----------------
    price_up = close_t > closes[t - 1] if t - 1 >= 0 else False
    mb_t, mb_p1 = margin_balance[t], margin_balance[t - 1] if t - 1 >= 0 else None
    margin_surge = False
    margin_flat_or_down = False
    if mb_t is not None and mb_p1 is not None and mb_p1 > 0:
        pct = (mb_t - mb_p1) / mb_p1
        margin_surge = price_up and pct > MARGIN_SURGE_THRESHOLD
        margin_flat_or_down = mb_t <= mb_p1
    cond4_pass = not margin_surge

    margin_adjust = 0.0
    if margin_surge:
        margin_adjust -= MARGIN_PENALTY_POINTS
        notes.append("⚠️股價漲但融資同步暴增(散戶追價，小心)")
    elif price_up and margin_flat_or_down:
        margin_adjust += 5.0
        notes.append("價漲、融資未增(甚至下降)，籌碼乾淨")

    # ---------------- ⑤ 突破/量能 ----------------
    ph_t = prior_high[t]
    va_t = vavg[t]
    breakout = ph_t is not None and close_t > ph_t
    vol_surge = va_t is not None and va_t > 0 and volume_t > va_t * VOLUME_SURGE_RATIO
    rng = high_t - low_t
    closed_near_high = True if rng <= 0 else ((high_t - close_t) / rng) <= LONG_UPPER_SHADOW_RATIO

    cond5_pass = bool(breakout and vol_surge and closed_near_high)

    if cond5_pass:
        volume_score = WEIGHT_VOLUME
        notes.append(f"帶量突破近{BREAKOUT_LOOKBACK}日高且收盤站穩")
    elif vol_surge and closed_near_high:
        volume_score = WEIGHT_VOLUME * 0.6
        notes.append("量增收紅但尚未突破前高")
    elif vol_surge and not closed_near_high:
        volume_score = WEIGHT_VOLUME * 0.2
        notes.append("⚠️爆量但留長上影線")
    elif vol_surge:
        volume_score = WEIGHT_VOLUME * 0.35
    else:
        volume_score = 0.0

    total_score = ma_score + chips_score + volume_score + kd_score + margin_adjust
    total_score = max(0.0, min(100.0, total_score))

    checklist_count = sum([cond1_pass, cond2_pass, cond3_pass, cond4_pass, cond5_pass])
    if checklist_count == 5:
        tier = "🔥主力觀察名單"
    elif checklist_count == 4:
        tier = "值得研究"
    elif checklist_count == 3:
        tier = "等待確認"
    else:
        tier = "先跳過"

    return {
        "market": market,
        "code": code,
        "name": name,
        "date": target_date,
        "close": close_t,
        "change_pct": (changes[t] / (close_t - changes[t]) * 100) if (close_t - changes[t]) else 0.0,
        "cond1_ma20": cond1_pass,
        "cond2_kd": cond2_pass,
        "cond3_chips": cond3_pass,
        "cond4_margin_ok": cond4_pass,
        "cond5_breakout_vol": cond5_pass,
        "checklist_count": checklist_count,
        "tier": tier,
        "score": round(total_score, 1),
        "notes": "；".join(notes),
    }


def run_screen(target_date: str, min_checklist: int = 3):
    results = []
    from config import MARKETS
    for market in MARKETS:
        codes = db.list_codes_with_price_on(market, target_date)
        for code, name in codes:
            try:
                r = evaluate_stock(market, code, name, target_date)
            except Exception as e:  # noqa: BLE001
                print(f"  [警告] {market} {code} 計算失敗，略過：{e}")
                continue
            if r and r["checklist_count"] >= min_checklist:
                results.append(r)

    results.sort(key=lambda r: (r["checklist_count"], r["score"]), reverse=True)
    return results
