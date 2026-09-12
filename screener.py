# -*- coding: utf-8 -*-
"""
核心選股邏輯：「KD打勾＋月線上＋籌碼轉強」＋動能／布林擴充版，共 7 條件 + 加權評分
======================================================================================
7 條件（達成數，對應打分表）：
  ① 股價站上 20 日月線
  ② KD 向上打勾（K 由下往上轉，最漂亮是 K 上穿 D）
  ③ 法人籌碼轉強（預設較嚴格：外資當天淨買超 且 投信連買 TRUST_CONSEC_BUY_DAYS 天，
                  兩者同時成立；可用 config.CHIPS_REQUIRE_FOREIGN_AND_TRUST 切回舊版「任一即算」）
  ④ 融資沒有暴增（股價漲＋融資也暴增 -> 不算過關；融資持平或下降更漂亮）
  ⑤ 突破或轉強有量（帶量突破前高/整理區，且收盤不是長上影線）
  ⑥ 動能指標同時成立：MACD 柱狀圖翻紅 + RSI 落在設定區間 + 5日線在10日線之上
  ⑦ 布林通道：收盤價在上軌（或設定容許範圍內），且上軌本身向上

成交量有一道「硬性門檻」（config.MIN_VOLUME_LOTS）：當天成交量（張）低於這個數字，
這檔股票直接不列入報表（流動性太差，不適合這套策略），不算在「不過關」裡面。

加權分數（0~100，用來在同一達成數級距內排序）：
  月線(30) ＞ 籌碼(25) ＞ 成交量(20) ＞ KD(10) ≈ 動能(10) ＞ 布林(5)；
  融資是風險濾網，暴增倒扣分數，融資乾淨則小幅加分。

大戶持股比例變化（選用，預設關閉，見 config.ENABLE_BIG_HOLDER_CHECK）：
  資料是集保中心一週一次的快照，不是每天都有新資料，所以只拿來當「加分參考」，
  不會影響③是否過關，避免因為週資料缺值而誤判。
"""

from indicators import calc_ma, calc_kd, volume_avg, rolling_prior_high, calc_macd, calc_rsi, calc_bollinger
import db
from config import (
    MA_PERIOD, MA_SLOPE_LOOKBACK, MA_JUST_RECLAIMED_LOOKBACK,
    KD_HIGH_ZONE, KD_STAGNANT_DAYS,
    CHIPS_REQUIRE_FOREIGN_AND_TRUST, TRUST_CONSEC_BUY_DAYS,
    MARGIN_SURGE_THRESHOLD, BREAKOUT_LOOKBACK, VOLUME_SURGE_RATIO,
    LONG_UPPER_SHADOW_RATIO, MIN_VOLUME_LOTS,
    MACD_TURN_LOOKBACK, RSI_MIN, RSI_MAX, MA_FAST, MA_MED,
    BB_SLOPE_LOOKBACK, BB_TOUCH_TOLERANCE,
    WEIGHT_MA20, WEIGHT_CHIPS, WEIGHT_VOLUME, WEIGHT_KD,
    WEIGHT_MOMENTUM, WEIGHT_BOLLINGER, MARGIN_PENALTY_POINTS,
    TIER_FULL_MIN, TIER_GOOD_MIN, TIER_WATCH_MIN,
    BACKFILL_TRADING_DAYS, ENABLE_BIG_HOLDER_CHECK,
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

    t = len(closes) - 1  # 今日索引
    close_t = closes[t]
    high_t, low_t = highs[t], lows[t]
    volume_t = volumes[t]

    # ---------------- 成交量硬性門檻（不是計分條件，是連篩選範圍都不進） ----------------
    volume_lots_t = volume_t / 1000.0 if volume_t is not None else 0.0
    if volume_lots_t < MIN_VOLUME_LOTS:
        return None

    ma20 = calc_ma(closes, MA_PERIOD)
    k_list, d_list = calc_kd(highs, lows, closes)
    vavg = volume_avg(volumes)
    prior_high = rolling_prior_high(highs, BREAKOUT_LOOKBACK)
    macd_line, signal_line, hist_line = calc_macd(closes)
    rsi_list = calc_rsi(closes)
    ma5 = calc_ma(closes, MA_FAST)
    ma10 = calc_ma(closes, MA_MED)
    bb_mid, bb_upper, bb_lower = calc_bollinger(closes)

    foreign_net, trust_net, total_net, margin_balance = _align_by_date(price_hist, insti_hist, margin_hist)

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
    f_t = foreign_net[t]
    f_p1 = foreign_net[t - 1] if t - 1 >= 0 else None
    tot_t = total_net[t]
    tot_p1 = total_net[t - 1] if t - 1 >= 0 else None
    trust_window = trust_net[max(0, t - TRUST_CONSEC_BUY_DAYS + 1): t + 1]
    trust_consec = len(trust_window) >= TRUST_CONSEC_BUY_DAYS and all(v > 0 for v in trust_window)

    if CHIPS_REQUIRE_FOREIGN_AND_TRUST:
        # 較嚴格版本：外資「當天淨買超」且投信「連買N天」要同時成立
        foreign_buy_today = f_t is not None and f_t > 0
        cond3_pass = bool(foreign_buy_today and trust_consec)
        chips_score = WEIGHT_CHIPS if cond3_pass else 0.0
        if foreign_buy_today:
            notes.append("外資當天淨買超")
        if trust_consec:
            notes.append(f"投信連買{TRUST_CONSEC_BUY_DAYS}日+")
        if cond3_pass:
            notes.append("外資+投信同步買超")
    else:
        # 舊版本：外資由賣轉買 / 投信連買 / 三大法人合計由賣轉買，任一即算
        foreign_flip = f_p1 is not None and f_p1 < 0 and f_t is not None and f_t > 0
        total_flip = tot_p1 is not None and tot_p1 < 0 and tot_t is not None and tot_t > 0
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

    # 大戶持股比例變化（選用，只當加分參考，不影響③是否過關，避免週資料缺值誤判）
    if ENABLE_BIG_HOLDER_CHECK:
        bh_hist = db.get_big_holder_history(code, target_date, limit_records=2)
        if len(bh_hist) == 2 and bh_hist[0][1] is not None and bh_hist[1][1] is not None:
            prev_pct, cur_pct = bh_hist[0][1], bh_hist[1][1]
            if cur_pct > prev_pct:
                chips_score = min(WEIGHT_CHIPS, chips_score + WEIGHT_CHIPS * 0.15)
                notes.append(f"大戶持股比例上升({prev_pct:.1f}%→{cur_pct:.1f}%)")
            elif cur_pct < prev_pct:
                notes.append(f"⚠️大戶持股比例下降({prev_pct:.1f}%→{cur_pct:.1f}%)")

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

    # ---------------- ⑥ 動能指標：MACD翻紅 + RSI區間 + 5日線穿10日線 ----------------
    hist_t = hist_line[t]
    macd_turn = False
    if hist_t is not None and hist_t > 0:
        lookback_window = hist_line[max(0, t - MACD_TURN_LOOKBACK): t]
        macd_turn = any(v is not None and v <= 0 for v in lookback_window)

    rsi_t = rsi_list[t]
    rsi_in_range = rsi_t is not None and RSI_MIN <= rsi_t <= RSI_MAX

    ma5_t, ma10_t = ma5[t], ma10[t]
    ma5_p1 = ma5[t - 1] if t - 1 >= 0 else None
    ma10_p1 = ma10[t - 1] if t - 1 >= 0 else None
    ma5_above = ma5_t is not None and ma10_t is not None and ma5_t > ma10_t
    ma5_fresh_cross = (
        ma5_above and ma5_p1 is not None and ma10_p1 is not None and ma5_p1 <= ma10_p1
    )

    cond6_pass = bool(macd_turn and rsi_in_range and ma5_above)
    if cond6_pass:
        momentum_score = WEIGHT_MOMENTUM
        detail = "MACD翻紅+RSI區間內"
        detail += "+5日線剛穿上10日線" if ma5_fresh_cross else "+5日線在10日線上"
        notes.append(detail)
    else:
        # 部分成立給一點點分數當排序參考，但不算過關
        partial = sum([macd_turn, rsi_in_range, ma5_above])
        momentum_score = WEIGHT_MOMENTUM * 0.25 * partial

    # ---------------- ⑦ 布林通道：站上上軌，且上軌向上 ----------------
    upper_t = bb_upper[t]
    upper_lag = bb_upper[t - BB_SLOPE_LOOKBACK] if t - BB_SLOPE_LOOKBACK >= 0 else None
    at_upper = (
        upper_t is not None and close_t is not None
        and close_t >= upper_t * (1 - BB_TOUCH_TOLERANCE)
    )
    upper_rising = upper_t is not None and upper_lag is not None and upper_t >= upper_lag
    cond7_pass = bool(at_upper and upper_rising)

    if cond7_pass:
        bollinger_score = WEIGHT_BOLLINGER
        notes.append("站上布林上軌且上軌向上(波動擴張)")
    elif at_upper:
        bollinger_score = WEIGHT_BOLLINGER * 0.4
    else:
        bollinger_score = 0.0

    total_score = (
        ma_score + chips_score + volume_score + kd_score
        + momentum_score + bollinger_score + margin_adjust
    )
    total_score = max(0.0, min(100.0, total_score))

    checklist_count = sum([
        cond1_pass, cond2_pass, cond3_pass, cond4_pass,
        cond5_pass, cond6_pass, cond7_pass,
    ])
    if checklist_count >= TIER_FULL_MIN:
        tier = "🔥主力觀察名單"
    elif checklist_count >= TIER_GOOD_MIN:
        tier = "值得研究"
    elif checklist_count >= TIER_WATCH_MIN:
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
        "cond6_momentum": cond6_pass,
        "cond7_bollinger": cond7_pass,
        "checklist_count": checklist_count,
        "tier": tier,
        "score": round(total_score, 1),
        "notes": "；".join(notes),
    }


def run_screen(target_date: str, min_checklist: int = TIER_WATCH_MIN):
    """回傳 (results, scanned_count)：
    results       通過門檻(checklist_count >= min_checklist)的股票，由高到低排序
    scanned_count 當天實際算得出分數的股票總數（不含資料不足、或成交量低於門檻被跳過的）
    """
    results = []
    scanned_count = 0
    from config import MARKETS
    for market in MARKETS:
        codes = db.list_codes_with_price_on(market, target_date)
        for code, name in codes:
            try:
                r = evaluate_stock(market, code, name, target_date)
            except Exception as e:  # noqa: BLE001
                print(f"  [警告] {market} {code} 計算失敗，略過：{e}")
                continue
            if r is None:
                continue
            scanned_count += 1
            if r["checklist_count"] >= min_checklist:
                results.append(r)

    results.sort(key=lambda r: (r["checklist_count"], r["score"]), reverse=True)
    return results, scanned_count
