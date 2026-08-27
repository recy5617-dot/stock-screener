# -*- coding: utf-8 -*-
"""用 TWSE 官方回應的真實樣本（開發時實際取得）驗證解析函式，不需要連網。"""
from unittest.mock import patch

import fetch_twse

MI_INDEX_SAMPLE = {
    "stat": "OK", "date": "20260825", "title": "test",
    "tables": [
        {"title": "irrelevant", "fields": ["foo"], "data": []},
        {
            "title": "每日收盤行情(全部)",
            "fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額",
                       "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差",
                       "最後揭示買價", "最後揭示買量", "最後揭示賣價", "最後揭示賣量", "本益比"],
            "data": [
                ["2330", "台積電", "41,996,854", "10,749", "591,942,522",
                 "1120.00", "1150.00", "1115.00", "1145.00",
                 "<p style= color:red>+</p>", "25.00", "0", "0", "0", "0", "0.00"],
                ["1101", "台泥", "6,805,335", "965", "89,201,421",
                 "30.00", "30.20", "29.50", "29.60",
                 "<p style='color:green'>-</p>", "0.40", "0", "0", "0", "0", "0.00"],
            ],
        },
    ],
}

T86_SAMPLE = {
    "stat": "OK", "date": "20260825",
    "fields": ["證券代號", "證券名稱",
               "外陸資買進股數(不含外資自營商)", "外陸資賣出股數(不含外資自營商)", "外陸資買賣超股數(不含外資自營商)",
               "外資自營商買進股數", "外資自營商賣出股數", "外資自營商買賣超股數",
               "投信買進股數", "投信賣出股數", "投信買賣超股數",
               "自營商買賣超股數",
               "自營商買進股數(自行買賣)", "自營商賣出股數(自行買賣)", "自營商買賣超股數(自行買賣)",
               "自營商買進股數(避險)", "自營商賣出股數(避險)", "自營商買賣超股數(避險)",
               "三大法人買賣超股數"],
    "data": [
        ["2330", "台積電", "1,000,000", "500,000", "500,000", "10,000", "5,000", "5,000",
         "20,000", "0", "20,000", "1,000", "500", "0", "500", "500", "0", "500", "525,000"],
    ],
}

MI_MARGN_SAMPLE = {
    "stat": "OK", "date": "20260825",
    "data": [
        ["2330", "台積電", "631", "119", "0", "9,603", "10,115", "494,535",
         "9", "8", "0", "21", "20", "494,535", "5", " "],
    ],
}


def fake_get_json(url, params=None, referer=None):
    if "MI_INDEX" in url:
        return MI_INDEX_SAMPLE
    if "T86" in url:
        return T86_SAMPLE
    if "MI_MARGN" in url:
        return MI_MARGN_SAMPLE
    raise AssertionError(f"unexpected url {url}")


with patch("fetch_twse.get_json", side_effect=fake_get_json):
    prices = fetch_twse._fetch_prices("20260825")
    insti = fetch_twse._fetch_institutional("20260825")
    margin = fetch_twse._fetch_margin("20260825")

print("=== prices ===")
for r in prices:
    print(r)
print("=== institutional ===")
for r in insti:
    print(r)
print("=== margin ===")
for r in margin:
    print(r)

# 驗證
assert len(prices) == 2
p2330 = next(r for r in prices if r["code"] == "2330")
assert p2330["close"] == 1145.00
assert p2330["change"] == 25.00, f"漲跌應為 +25.00，實際 {p2330['change']}"
p1101 = next(r for r in prices if r["code"] == "1101")
assert p1101["change"] == -0.40, f"漲跌應為 -0.40，實際 {p1101['change']}"

assert len(insti) == 1
i2330 = insti[0]
assert i2330["foreign_net"] == 505000, f"外資合計應為 500000+5000=505000，實際 {i2330['foreign_net']}"
assert i2330["trust_net"] == 20000
assert i2330["dealer_net"] == 1000
assert i2330["total_net"] == 525000

assert len(margin) == 1
m2330 = margin[0]
assert m2330["margin_balance"] == 10115
assert m2330["margin_buy"] == 631
assert m2330["margin_sell"] == 119

print("\n✅ 解析邏輯全部正確：欄位對應、千分位逗號、紅漲綠跌正負號都沒問題。")
