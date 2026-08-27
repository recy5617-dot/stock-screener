# -*- coding: utf-8 -*-
"""
【模擬展示用】不是真的市場資料，只是用假造但型態合理的股價/籌碼/融資資料，
餵進真正的 evaluate_stock() 選股邏輯，讓你先看看「報表長什麼樣子」。
不連網、不影響正式快取，跑完會自動清掉暫存 DB。
"""
import os
import random
from datetime import datetime, timedelta

import db
from config import DB_PATH
from screener import evaluate_stock

random.seed(7)
TEST_DB = DB_PATH + ".demo"
db.DB_PATH = TEST_DB
import config as _cfg
_cfg.DB_PATH = TEST_DB
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
db.init_db()

MARKET = "TWSE"


def biz_dates(n, end=datetime(2026, 8, 25)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    out.reverse()
    return [dt.strftime("%Y%m%d") for dt in out]


dates = biz_dates(60)
n = len(dates)
target = dates[-1]


def gen_stock(code, name, close_path, vol_path, foreign_path, trust_path, margin_path,
              hi_extra=None, lo_extra=None):
    """close_path/vol_path/foreign_path/trust_path/margin_path: 長度 n 的 list"""
    prices, insti, margin = [], [], []
    for i, d in enumerate(dates):
        c = close_path[i]
        c_prev = close_path[i - 1] if i > 0 else c
        o = c_prev
        extra_h = hi_extra[i] if hi_extra else 0.0
        extra_l = lo_extra[i] if lo_extra else 0.0
        h = max(o, c) + 0.2 + extra_h
        l = min(o, c) - 0.2 - extra_l
        prices.append({
            "date": d, "market": MARKET, "code": code, "name": name,
            "open": o, "high": h, "low": l, "close": c,
            "volume": vol_path[i], "change": c - c_prev,
        })
        f = foreign_path[i]
        t = trust_path[i]
        insti.append({
            "date": d, "market": MARKET, "code": code,
            "foreign_net": f, "trust_net": t, "dealer_net": 0, "total_net": f + t,
        })
        margin.append({
            "date": d, "market": MARKET, "code": code,
            "margin_buy": 5, "margin_sell": 5, "margin_balance": margin_path[i],
        })
    db.save_prices(prices)
    db.save_institutional(insti)
    db.save_margin(margin)


stocks = []

# ---- 1. 台強科技(模擬)：完美型態，5/5 ----
close = [45 + i * 0.125 for i in range(40)] + [50 - (i) * 0.15 for i in range(19)] + [55.0]
vol = [2600 + (i % 5) * 20 for i in range(59)] + [17000]
foreign = [0] * 57 + [-100, -50, 900]
trust = [0] * 57 + [40, 60, 320]
margin = [10000 - i * 3 for i in range(n)]
gen_stock("1101", "台強科技(模擬)", close, vol, foreign, trust, margin,
          hi_extra=[0]*59 + [0.0], lo_extra=[0]*n)
stocks.append(("1101", "台強科技(模擬)"))

# ---- 2. 佳信電子(模擬)：4/5，只差還沒放量突破（籌碼/月線/KD都對）----
close = [40 + i * 0.1 for i in range(40)] + [44 - i * 0.1 for i in range(19)] + [45.6]
vol = [2000 + (i % 4) * 15 for i in range(60)]  # 量沒有明顯放大
foreign = [0] * 57 + [-80, -40, 260]
trust = [0] * 57 + [30, 50, 180]
margin = [8000 - i * 2 for i in range(n)]
gen_stock("2202", "佳信電子(模擬)", close, vol, foreign, trust, margin)
stocks.append(("2202", "佳信電子(模擬)"))

# ---- 3. 宏運材料(模擬)：4/5，量價都對但融資暴增（風險警示）----
close = [30 + i * 0.1 for i in range(40)] + [34 - i * 0.08 for i in range(19)] + [37.0]
vol = [2200 + (i % 5) * 20 for i in range(59)] + [12000]
foreign = [0] * 57 + [-60, -30, 200]
trust = [0] * 57 + [20, 40, 150]
_margin_lead = [6000 + i * 5 for i in range(n - 1)]
margin = _margin_lead + [_margin_lead[-1] * 1.08]  # 最後一天融資餘額比前一天暴增8%
gen_stock("3303", "宏運材料(模擬)", close, vol, foreign, trust, margin)
stocks.append(("3303", "宏運材料(模擬)"))

# ---- 4. 群鴻生技(模擬)：3/5，月線剛站上、籌碼轉強，但KD還沒打勾、量普通 ----
close = [25 - i * 0.02 for i in range(40)] + [24.2 + i * 0.08 for i in range(20)]
vol = [1800 + (i % 4) * 10 for i in range(60)]
foreign = [0] * 58 + [-30, 90]
trust = [0] * 59 + [40]
margin = [4000 - i * 1 for i in range(n)]
gen_stock("4404", "群鴻生技(模擬)", close, vol, foreign, trust, margin)
stocks.append(("4404", "群鴻生技(模擬)"))

# ---- 5. 東海食品(模擬)：反例，0~1/5，月線下盤旋、法人賣超、融資增、量縮 ----
close = [20 - i * 0.03 for i in range(n)]
vol = [900 - (i % 3) * 10 for i in range(n)]
foreign = [-150] * n
trust = [-40] * n
margin = [3000 + i * 30 for i in range(n)]
gen_stock("5505", "東海食品(模擬)", close, vol, foreign, trust, margin)
stocks.append(("5505", "東海食品(模擬)"))

# ---- 6. 元穎光電(模擬)：反例，高檔鈍化後才打勾，KD分數會被降權 ----
close = [30 + i * 0.35 for i in range(35)] + [42 + random.uniform(-0.3, 0.3) for i in range(22)] + [42.5, 42.3, 43.5]
vol = [3000] * n
foreign = [50] * n
trust = [10] * n
margin = [5000] * n
gen_stock("6606", "元穎光電(模擬)", close, vol, foreign, trust, margin)
stocks.append(("6606", "元穎光電(模擬)"))

results = []
for code, name in stocks:
    r = evaluate_stock(MARKET, code, name, target)
    if r:
        results.append(r)

results.sort(key=lambda r: (r["checklist_count"], r["score"]), reverse=True)

MIN_CHECKLIST = 3
shown = [r for r in results if r["checklist_count"] >= MIN_CHECKLIST]

print(f"【模擬展示，非真實市場資料】目標日期：{target}")
print(f"模擬掃描 {len(results)} 檔，符合門檻(達成>={MIN_CHECKLIST}項) {len(shown)} 檔\n")
header = f"{'代號':<6}{'名稱':<16}{'收盤':>8}{'漲跌%':>8}  {'①月線':<6}{'②KD':<6}{'③籌碼':<6}{'④融資':<6}{'⑤量':<6}{'達成':<5}{'分級':<12}{'加權分':>7}"
print(header)
print("-" * 110)
for r in results:
    mark = "✅" if r["checklist_count"] >= MIN_CHECKLIST else "  "
    print(
        f"{r['code']:<6}{r['name']:<16}{r['close']:>8.2f}{r['change_pct']:>7.2f}%  "
        f"{'✅' if r['cond1_ma20'] else '❌':<6}{'✅' if r['cond2_kd'] else '❌':<6}"
        f"{'✅' if r['cond3_chips'] else '❌':<6}{'✅' if r['cond4_margin_ok'] else '❌':<6}"
        f"{'✅' if r['cond5_breakout_vol'] else '❌':<6}{r['checklist_count']:<5}{r['tier']:<12}"
        f"{r['score']:>7.1f}"
    )
print()
for r in results:
    print(f"[{r['code']} {r['name']}] {r['notes']}")

# 輸出成 CSV 方便你看
import csv
out_path = "/home/claude/stock_screener_demo_output.csv"
fieldnames = ["market","code","name","date","close","change_pct","cond1_ma20","cond2_kd",
              "cond3_chips","cond4_margin_ok","cond5_breakout_vol","checklist_count","tier","score","notes"]
with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for r in results:
        w.writerow(r)
print(f"\n已輸出 CSV: {out_path}")

import report as _report
_demo_docs = "/home/claude/stock_screener_demo_docs"
_report.write_reports(shown, target, len(results), MIN_CHECKLIST, _demo_docs)
print(f"已輸出網頁報表: {os.path.join(_demo_docs, 'index.html')}")

os.remove(TEST_DB)
