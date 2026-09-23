# -*- coding: utf-8 -*-
"""「我的關注」頁資料測試（不需要連網）：當天價格、漲跌%、是否進波段/當沖名單，以及頁面不會被股票名稱截斷。

    python test_watchlist.py
"""
import json
import os
import re
import tempfile

import report

prices = [("2330", "台積電", 1145.0, 25.0), ("1101", "台泥", 29.6, -0.4), ("9999", "怪名</script>", 10.0, 0.0)]
swing = [{"code": "2330", "tier": "值得研究", "checklist_count": 5, "score": 82.5}]
dt = [{"code": "1101", "side": "空", "score": 71.2}]

snap = report.build_watchlist_snapshot("20260825", prices, swing, dt)
s = snap["stocks"]
assert s["2330"] == {"n": "台積電", "c": 1145.0, "p": 2.23, "s": "值得研究 5/7・82.5分"}, s["2330"]
assert s["1101"]["p"] == -1.33 and s["1101"]["d"] == "偏空・71.2分" and "s" not in s["1101"], s["1101"]

with tempfile.TemporaryDirectory() as d:
    report.write_watchlist_page(snap, d)
    html = open(os.path.join(d, "watchlist.html"), encoding="utf-8").read()
m = re.search(r'<script type="application/json" id="wl-data">(.*?)</script>', html, re.S)
assert m, "找不到內嵌資料"
assert json.loads(m.group(1))["stocks"]["9999"]["n"] == "怪名</script>", "股票名稱含 </script> 時資料要完整"
assert 'src="watchlist.js"' in html and 'id="wl-root"' in html

# 波段/當沖頁的卡片要帶 data-code，關注按鈕才掛得上去
card = report._render_card({"name": "台積電", "code": "2330", "market": "TWSE", "close": 1145.0, "change_pct": 2.2,
                            "tier": "值得研究", "checklist_count": 5, "score": 82.5, "notes": ""})
assert 'data-code="2330"' in card
page = report.render_report_html([], "20260825", 0, 3, is_index=False)
assert 'src="../watchlist.js"' in page and 'href="../watchlist.html"' in page

print("✅ 我的關注頁資料測試通過")
