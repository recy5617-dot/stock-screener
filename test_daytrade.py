# -*- coding: utf-8 -*-
"""
當沖候選名單自我測試（不需要連網）
==================================
建立幾檔合成股票，餵進 evaluate_daytrade() 驗證：
  X 強勢多方：波動夠、爆量、收最高、突破20日高、法人買 -> 應該高分、方向=多
  Y 弱勢空方：波動夠、爆量、收最低、跌破20日低、法人賣 -> 應該高分、方向=空
  Z 牛皮股  ：成交量大但每天只動一點點（ATR很小）   -> 波動條件不過、分數低
  W 冷門股  ：成交量低於硬性門檻                      -> 直接不列入（None）
另外驗證官方可當沖清單的效果：不在清單上 -> 排除；「暫停先賣後買」-> 偏空排除。
也用樣本資料驗證 TWTB4U 解析。

    python test_daytrade.py
"""
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import db
from config import DB_PATH

TEST_DB = DB_PATH + ".dt_test"
db.DB_PATH = TEST_DB
import config as _cfg
_cfg.DB_PATH = TEST_DB

import fetch_twse
from daytrade import evaluate_daytrade, calc_atr

MARKET = "TWSE"

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


dates = biz_dates(40)
target = dates[-1]


def build(code, name, closes, swing, last_bar, base_vol, last_vol, foreign_last):
    """closes: 每日收盤；swing: 平日高低點離收盤的距離；last_bar: 最後一天 (high, low)。"""
    prices, insti = [], []
    for i, d in enumerate(dates):
        c = closes[i]
        c_prev = closes[i - 1] if i > 0 else c
        if i == len(dates) - 1:
            h, l = last_bar
            vol = last_vol
        else:
            h, l = max(c, c_prev) + swing, min(c, c_prev) - swing
            vol = base_vol
        prices.append({"date": d, "market": MARKET, "code": code, "name": name,
                       "open": c_prev, "high": h, "low": l, "close": c, "volume": vol, "change": c - c_prev})
        insti.append({"date": d, "market": MARKET, "code": code,
                      "foreign_net": foreign_last if i == len(dates) - 1 else 0,
                      "trust_net": 0, "dealer_net": 0, "total_net": 0})
    db.save_prices(prices)
    db.save_institutional(insti)


# X：100 元附近來回震盪（每天振幅約4%），最後一天爆量拉到 106 收最高
x_closes = [100 + (1.5 if i % 2 else -1.5) for i in range(len(dates) - 1)] + [106.0]
build("1001", "測試多方", x_closes, 1.0, (106.2, 101.0), 5_000_000, 15_000_000, 500_000)

# Y：鏡像，最後一天爆量殺到 94 收最低
y_closes = [100 + (1.5 if i % 2 else -1.5) for i in range(len(dates) - 1)] + [94.0]
build("1002", "測試空方", y_closes, 1.0, (99.0, 93.8), 5_000_000, 15_000_000, -500_000)

# Z：量很大但每天只動 0.1 元（ATR ~0.3%），最後一天小漲
z_closes = [50 + (0.05 if i % 2 else -0.05) for i in range(len(dates) - 1)] + [50.1]
build("1003", "測試牛皮", z_closes, 0.05, (50.15, 50.0), 20_000_000, 20_000_000, 0)

# W：型態跟 X 一樣但只有 500 張
build("1004", "測試冷門", x_closes, 1.0, (106.2, 101.0), 400_000, 500_000, 500_000)

rx = evaluate_daytrade(MARKET, "1001", "測試多方", target)
ry = evaluate_daytrade(MARKET, "1002", "測試空方", target)
rz = evaluate_daytrade(MARKET, "1003", "測試牛皮", target)
rw = evaluate_daytrade(MARKET, "1004", "測試冷門", target)

for label, r in [("X 強勢多方", rx), ("Y 弱勢空方", ry), ("Z 牛皮股", rz), ("W 冷門股", rw)]:
    print(f"--- {label} ---")
    if r is None:
        print("  None（被硬性濾網排除）")
    else:
        for k in ("side", "score", "atr_pct", "vol_ratio", "close_pos", "checklist_count", "r1", "s1", "notes"):
            print(f"  {k}: {r[k]}")

assert rx is not None and rx["side"] == "多", rx
assert rx["condA_volatility"] and rx["condC_volume"] and rx["condD_close"] and rx["condE_trend"] and rx["condF_chips"]
assert rx["score"] >= 80, rx["score"]

assert ry is not None and ry["side"] == "空", ry
assert ry["condD_close"] and ry["condE_trend"] and ry["condF_chips"]
assert ry["score"] >= 80, ry["score"]

assert rz is not None and not rz["condA_volatility"], rz
assert rz["score"] < 60, f"牛皮股不應進名單，實際 {rz['score']}"

assert rw is None, "成交量低於門檻應被排除"

# ATR 基本檢查：固定振幅 2、無跳空 -> ATR = 2
atr = calc_atr([11] * 20, [9] * 20, [10] * 20, period=14)
assert abs(atr[-1] - 2.0) < 1e-9 and atr[13] is None

# 官方可當沖清單：不在清單 -> 排除；暫停先賣後買 -> 偏空排除、偏多不受影響
dt_list = {"1001": (True, 3_000_000), "1002": (True, 3_000_000)}
assert evaluate_daytrade(MARKET, "1003", "測試牛皮", target, dt_list) is None
assert evaluate_daytrade(MARKET, "1002", "測試空方", target, dt_list) is None
rx2 = evaluate_daytrade(MARKET, "1001", "測試多方", target, dt_list)
assert rx2 is not None and rx2["daytrade_ratio"] == 20.0, rx2
assert evaluate_daytrade(MARKET, "1002", "測試空方", target, {"1002": (False, None)}) is not None

# TWTB4U 解析：用欄位名稱找表格，註記有值 = 暫停先賣後買
TWTB4U_SAMPLE = {
    "stat": "OK", "date": target,
    "tables": [
        {"title": "當日沖銷交易統計", "fields": ["當日沖銷交易總成交股數", "當日沖銷交易總成交股數占市場比重%"],
         "data": [["1,000", "30.00"]]},
        {"title": "當日沖銷交易標的及成交量值",
         "fields": ["證券代號", "證券名稱", "暫停現股賣出後現款買進當沖註記",
                    "當日沖銷交易成交股數", "當日沖銷交易買進成交金額", "當日沖銷交易賣出成交金額"],
         "data": [["2330", "台積電", "", "12,345,000", "1", "1"],
                  ["2409", "友達", "Y", "50,000,000", "1", "1"]]},
    ],
}
with patch("fetch_twse.get_json", return_value=TWTB4U_SAMPLE):
    rows = fetch_twse._fetch_daytrade_list(target)
assert len(rows) == 2, rows
assert rows[0]["code"] == "2330" and rows[0]["sell_first_suspended"] == 0 and rows[0]["daytrade_volume"] == 12_345_000
assert rows[1]["code"] == "2409" and rows[1]["sell_first_suspended"] == 1
with patch("fetch_twse.get_json", return_value={"stat": "OK", "tables": [{"fields": ["foo"], "data": [["x"]]}]}):
    assert fetch_twse._fetch_daytrade_list(target) == [], "格式對不上應回傳空 list（不套用濾網）"

print("\n✅ 當沖選股測試通過：多空方向判斷、波動/量能/收盤/順勢/法人評分、硬性濾網、可當沖清單濾網與解析都正確。")

os.remove(TEST_DB)
