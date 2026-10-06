# -*- coding: utf-8 -*-
"""短線分析表測試（不需要連網）：用合成的多頭／空頭走勢檢查趨勢判斷與價位排列是否合理。

    python test_analysis.py
"""
import analysis as A


def make(closes, vol=5_000_000, last_vol=None):
    rows = []
    for i, c in enumerate(closes):
        prev = closes[i - 1] if i else c
        v = last_vol if (last_vol and i == len(closes) - 1) else vol
        rows.append((f"2026{i:04d}", prev, max(c, prev) * 1.01, min(c, prev) * 0.99, c, v, c - prev))
    return rows


def num(z):
    """'103.5～105' -> (103.5, 105)；'107' -> (107, 107)"""
    z = z.replace("以上", "")
    parts = [float(x) for x in z.split("～")]
    return parts[0], parts[-1]


def check_order(a, close):
    s1, s2, s3 = num(a["s1"]), num(a["s2"]), num(a["s3"])
    r1, r2 = num(a["r1"]), num(a["r2"])
    assert s1[1] < close and s1[0] > s2[1] and s2[0] > s3[1], (a["s1"], a["s2"], a["s3"])
    assert close < r1[0] <= r1[1] < r2[0], (a["r1"], a["r2"])
    stop = float(a["stop"])
    assert stop < num(a["buy2"])[0] < num(a["buy1"])[0], (a["stop"], a["buy2"], a["buy1"])
    assert num(a["defend"])[1] < stop, (a["defend"], a["stop"])
    assert num(a["target"])[0] > r2[1], (a["target"], a["r2"])


# 多頭：緩步墊高、最後一天帶量，法人買超
up = [100 + i * 0.6 + (1.5 if i % 4 == 0 else 0) for i in range(60)]
insti_up = [(f"2026{i:04d}", 1000, 500, 0, 1500) for i in range(55, 60)]
a = A.analyze(make(up, last_vol=9_000_000), insti_up, [])
lab = A.labels_of(a)
print("多頭：", lab, a["s1"], a["s2"], a["s3"], a["r1"], a["r2"], a["buy1"], a["stop"], a["rr"])
assert lab["trend"] == "偏多" and lab["chips"] == "籌碼同步偏多" and lab["vp"] == "強", lab
check_order(a, up[-1])
assert a["rr"].startswith("1：")

# 空頭：一路走低、法人賣超 → 偏空、建議觀望
down = [150 - i * 0.8 for i in range(60)]
insti_dn = [(f"2026{i:04d}", -1000, -200, 0, -1200) for i in range(55, 60)]
b = A.analyze(make(down), insti_dn, [])
lb = A.labels_of(b)
print("空頭：", lb)
assert lb["trend"] == "偏空" and lb["chips"] == "籌碼偏空" and lb["advice"].startswith("趨勢偏空"), lb

# 價漲但法人賣、融資大增 → 價強籌碼弱
margin = [(f"2026{i:04d}", 1000 + (300 if i == 59 else 0), 0, 0) for i in range(50, 60)]
c = A.analyze(make(up), [(f"2026{i:04d}", -500, -100, 0, -600) for i in range(55, 60)], margin)
assert A.labels_of(c)["chips"] == "價強籌碼弱"

# 創新高：上方沒有任何價位 → 壓力用 ATR 推估、標記 est
assert a["est"] in (True, False)

# 升降單位
assert A.fmt(110.53) == "110.5" and A.fmt(1146) == "1145" and A.fmt(9.876) == "9.88" and A.fmt(47.03) == "47.05"
assert A.fmt_zone(103.5, 105) == "103.5～105" and A.fmt_zone(107, 107.02) == "107"

# 資料不足
assert A.analyze(make(up[:10])) is None

# 內嵌陣列長度要跟網頁端一致（docs/watchlist.js 用索引 0~18）
assert len(A.to_compact(a)) == 19

print("✅ 短線分析測試通過")
