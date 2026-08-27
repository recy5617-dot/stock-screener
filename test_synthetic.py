# -*- coding: utf-8 -*-
"""
合成資料自我測試（不需要連網）
================================
建立一檔「完全符合5條件」的理想型態股票 A、一檔「完全不符合」的反例股票 B，
餵進 evaluate_stock() 驗證計分邏輯是否如預期運作。

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
            vol = 16000                  # 明顯爆量
        else:
            h, l = max(o, c) + 0.25, min(o, c) - 0.25
            vol = 2600 + (i % 5) * 20    # 平日量能穩定、偏低

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
        vol = 1000 - (i % 3) * 10
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


build_stock_a()
build_stock_b()

target = dates[-1]
print(f"目標日期: {target}\n")

r_a = evaluate_stock(MARKET, "1111", "測試強勢", target)
r_b = evaluate_stock(MARKET, "2222", "測試轉弱", target)

for label, r in [("股票A(理想型態，預期應接近5/5)", r_a), ("股票B(反例，預期應接近0/5)", r_b)]:
    print(f"--- {label} ---")
    if r is None:
        print("  evaluate_stock 回傳 None（資料不足或當天無資料）")
        continue
    for k, v in r.items():
        print(f"  {k}: {v}")
    print()

assert r_a is not None and r_b is not None, "不應該是 None"
assert r_a["checklist_count"] >= 4, f"股票A理應接近全過關，實際 {r_a['checklist_count']}"
assert r_b["checklist_count"] <= 1, f"股票B理應幾乎不過關，實際 {r_b['checklist_count']}"
assert r_a["score"] > r_b["score"], "股票A加權分數應明顯高於股票B"
print("✅ 測試通過：理想型態高分過關、反例低分被濾掉，邏輯符合你設定的規則。")

os.remove(TEST_DB)
for ext in ("-wal", "-shm"):
    p = TEST_DB + ext
    if os.path.exists(p):
        os.remove(p)
