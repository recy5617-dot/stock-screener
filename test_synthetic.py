# -*- coding: utf-8 -*-
"""
合成資料自我測試（不需要連網）
================================
建立一檔「絕大部分條件都符合」的理想型態股票 A、一檔「幾乎都不符合」的反例股票 B，
餵進 evaluate_stock() 驗證計分邏輯是否如預期運作（現在共 7 條件）。

股票A刻意用「單日大爆量突破」呈現，這種型態通常會讓 RSI 衝上超買區(>70)，
所以⑥動能條件(要求 RSI 落在 50~70 之間，避免追高)不會過關，這是符合設計初衷的
正常結果，不是bug —— ⑤突破/量能 跟 ⑥非超買動能 本來就會在「單日噴出」時互相制衡。

任何時候想確認「這套邏輯到底有沒有抓對你講的規則」，都可以直接執行：
    python test_synthetic.py
不需要網路、不會動到正式的快取資料庫。
"""
import os
from datetime import datetime, timedelta

import db
from config import DB_PATH
from screener import evaluate_stock

MARKET = "TWSE"
TEST_DB = DB_PATH + ".test"

# 讓 db 模組寫去一個獨立的測試檔，不影響正式快取
db.DB_PATH = TEST_DB
import config as _cfg
_cfg.DB_PATH = TEST_DB

if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
db.init_db()


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


def build_stock_a():
    """理想型態：緩步墊高 -> 末段小幅拉回打出KD低點 -> 最後一天帶量突破、收盤貼近最高、
    法人轉買、融資平穩。"""
    prices, insti, margin = [], [], []
    closes = []
    for i in range(n):
        if i < 40:
            c = 45 + i * 0.125          # 40天緩步墊高 45 -> 50
        elif i < 58:
            c = 50 - (i - 39) * 0.15    # 末段小拉回 ~47.1，製造KD由高轉低
        elif i == 58:
            c = 47.0                    # 倒數第2天：低點打底
        else:
            c = 55.0                    # 最後一天：帶量大漲，突破前波高點
        closes.append(c)

    for i, d in enumerate(dates):
        c = closes[i]
        c_prev = closes[i - 1] if i > 0 else c
        o = c_prev
        if i == n - 1:
            h, l = 55.3, 53.0            # 收盤貼近最高，非長上影線
            vol = 16_000_000              # 明顯爆量（16000張，遠高於流動性門檻）
        else:
            h, l = max(o, c) + 0.25, min(o, c) - 0.25
            vol = 2_600_000 + (i % 5) * 20_000  # 平日量能穩定，約2600張，高於1000張門檻

        prices.append({
            "date": d, "market": MARKET, "code": "1111", "name": "測試強勢",
            "open": o, "high": h, "low": l, "close": c, "volume": vol, "change": c - c_prev,
        })

        if i == n - 1:
            f_net, tr_net = 800, 300     # 最後一天外資由賣轉買、投信同步買
        elif i == n - 2:
            f_net, tr_net = -100, 60     # 前一天：外資仍賣、投信已開始買（連買第1天）
        elif i == n - 3:
            f_net, tr_net = -50, 40      # 投信連買第0天起點
        else:
            f_net, tr_net = 0, 0
        insti.append({
            "date": d, "market": MARKET, "code": "1111",
            "foreign_net": f_net, "trust_net": tr_net, "dealer_net": 0,
            "total_net": f_net + tr_net,
        })

        mb = 10000 - i * 3               # 融資緩降，股價漲、融資沒有暴增
        margin.append({"date": d, "market": MARKET, "code": "1111",
                        "margin_buy": 5, "margin_sell": 8, "margin_balance": mb})

    db.save_prices(prices)
    db.save_institutional(insti)
    db.save_margin(margin)


def build_stock_b():
    """反例：股價在月線下盤旋緩跌、法人持續賣超、融資持續增加、量能萎縮。"""
    prices, insti, margin = [], [], []
    closes = [30 - i * 0.05 for i in range(n)]
    for i, d in enumerate(dates):
        c = closes[i]
        c_prev = closes[i - 1] if i > 0 else c
        o = c_prev
        h, l = max(o, c) + 0.4, min(o, c) - 0.6
        vol = 1_500_000 - (i % 3) * 10_000  # 約1500張，高於門檻，確保會被評分(而不是被流動性濾網濾掉)
        prices.append({
            "date": d, "market": MARKET, "code": "2222", "name": "測試轉弱",
            "open": o, "high": h, "low": l, "close": c, "volume": vol, "change": c - c_prev,
        })
        insti.append({
            "date": d, "market": MARKET, "code": "2222",
            "foreign_net": -200, "trust_net": -50, "dealer_net": 0, "total_net": -250,
        })
        mb = 5000 + i * 40
        margin.append({"date": d, "market": MARKET, "code": "2222",
                        "margin_buy": 100, "margin_sell": 20, "margin_balance": mb})
    db.save_prices(prices)
    db.save_institutional(insti)
    db.save_margin(margin)


def build_stock_c():
    """專門驗證⑥動能條件(MACD翻紅+RSI區間+5日線穿10日線)：用「和緩多日回升」取代股票A的
    單日爆量突破，這樣RSI才不會一次衝進超買區，能停留在50~70的區間。"""
    dates_c = biz_dates(64)
    rate = 0.004
    closes_c = []
    for i in range(len(dates_c)):
        if i < 40:
            c = 45 + i * 0.125
        elif i < 58:
            c = 50 - (i - 39) * 0.10
        else:
            c = closes_c[-1] * (1 + rate)
        closes_c.append(c)

    prices, insti, margin = [], [], []
    for i, d in enumerate(dates_c):
        c = closes_c[i]
        c_prev = closes_c[i - 1] if i > 0 else c
        o = c_prev
        if i >= 58:
            h, l = c * 1.004, c_prev * 0.999
            vol = 4_000_000
        else:
            h, l = max(o, c) + 0.2, min(o, c) - 0.2
            vol = 2_600_000 + (i % 5) * 20_000
        prices.append({
            "date": d, "market": MARKET, "code": "3333", "name": "測試動能",
            "open": o, "high": h, "low": l, "close": c, "volume": vol, "change": c - c_prev,
        })
        insti.append({
            "date": d, "market": MARKET, "code": "3333",
            "foreign_net": 0, "trust_net": 0, "dealer_net": 0, "total_net": 0,
        })
        margin.append({"date": d, "market": MARKET, "code": "3333",
                        "margin_buy": 5, "margin_sell": 5, "margin_balance": 8000})
    db.save_prices(prices)
    db.save_institutional(insti)
    db.save_margin(margin)
    return dates_c[-1]


build_stock_a()
build_stock_b()
target_c = build_stock_c()

target = dates[-1]
print(f"目標日期: {target}\n")

r_a = evaluate_stock(MARKET, "1111", "測試強勢", target)
r_b = evaluate_stock(MARKET, "2222", "測試轉弱", target)
r_c = evaluate_stock(MARKET, "3333", "測試動能", target_c)

for label, r in [("股票A(理想型態，預期應接近全過關/7)", r_a), ("股票B(反例，預期應接近0/7)", r_b)]:
    print(f"--- {label} ---")
    if r is None:
        print("  evaluate_stock 回傳 None（資料不足、當天無資料，或成交量低於流動性門檻）")
        continue
    for k, v in r.items():
        print(f"  {k}: {v}")
    print()

print(f"--- 股票C(專測⑥動能條件，和緩多日回升) ---")
if r_c is None:
    print("  evaluate_stock 回傳 None（資料不足或當天無資料）")
else:
    for k, v in r_c.items():
        print(f"  {k}: {v}")
print()

assert r_a is not None and r_b is not None, "不應該是 None"
assert r_a["checklist_count"] >= 5, f"股票A理應大部分過關(>=5/7)，實際 {r_a['checklist_count']}"
assert r_b["checklist_count"] <= 2, f"股票B理應幾乎不過關(<=2/7)，實際 {r_b['checklist_count']}"
assert r_a["score"] > r_b["score"], "股票A加權分數應明顯高於股票B"

assert r_c is not None, "股票C不應該是 None"
assert r_c["cond6_momentum"] is True, f"股票C理應觸發⑥動能條件，實際 {r_c['cond6_momentum']}"
print("✅ 測試通過：理想型態高分過關、反例低分被濾掉、⑥動能條件在和緩回升情境下能正確觸發，邏輯符合你設定的規則。")

os.remove(TEST_DB)
for ext in ("-wal", "-shm"):
    p = TEST_DB + ext
    if os.path.exists(p):
        os.remove(p)
