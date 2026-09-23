# -*- coding: utf-8 -*-
"""
產生每日選股的 HTML 報表（給 GitHub Pages 用）
==================================================
跟 main.py 輸出的 CSV 是同一份資料，只是排版成手機看起來比較舒服的網頁卡片，
放進 docs/ 資料夾，搭配 GitHub Pages 就會有一個固定網址可以每天打開看。
不依賴任何外部 CDN / 字型，純內嵌 CSS，離線也能開。
"""

import os
import html as html_lib

from config import TOTAL_CONDITIONS

TIER_CLASS = {
    "🔥主力觀察名單": "tier-fire",
    "值得研究": "tier-good",
    "等待確認": "tier-watch",
    "先跳過": "tier-skip",
}

COND_LABELS = [
    ("cond1_ma20", "①月線"),
    ("cond2_kd", "②KD"),
    ("cond3_chips", "③籌碼"),
    ("cond4_margin_ok", "④融資"),
    ("cond5_breakout_vol", "⑤量"),
    ("cond6_momentum", "⑥動能"),
    ("cond7_bollinger", "⑦布林"),
]

BASE_CSS = """<style>
  :root {{
    --bg: #f5f6f8;
    --card-bg: #ffffff;
    --text: #1a1d23;
    --muted: #6b7280;
    --border: #e5e7eb;
    --fire: #dc2626;
    --fire-bg: #fef2f2;
    --good: #2563eb;
    --good-bg: #eff6ff;
    --watch: #6b7280;
    --watch-bg: #f3f4f6;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang TC", "Microsoft JhengHei", sans-serif;
    line-height: 1.5;
  }}
  header {{
    padding: 20px 16px 12px;
    max-width: 900px;
    margin: 0 auto;
  }}
  h1 {{ font-size: 1.3rem; margin: 0 0 4px; }}
  .subtitle {{ color: var(--muted); font-size: 0.9rem; }}
  .disclaimer {{
    max-width: 900px; margin: 0 auto 16px; padding: 10px 16px;
    background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px;
    font-size: 0.82rem; color: #92400e;
  }}
  main {{ max-width: 900px; margin: 0 auto; padding: 0 16px 40px; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 12px;
  }}
  .card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }}
  .card-top {{
    display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;
  }}
  .name {{ font-weight: 600; font-size: 1.02rem; }}
  .code {{ color: var(--muted); font-size: 0.85rem; }}
  .price {{ text-align: right; }}
  .close {{ font-weight: 600; font-size: 1.05rem; }}
  .change-up {{ color: var(--fire); font-size: 0.85rem; }}
  .change-down {{ color: #16a34a; font-size: 0.85rem; }}
  .badge {{
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    font-size: 0.78rem; font-weight: 600; margin-top: 8px;
  }}
  .tier-fire {{ background: var(--fire-bg); color: var(--fire); }}
  .tier-good {{ background: var(--good-bg); color: var(--good); }}
  .tier-watch {{ background: var(--watch-bg); color: var(--watch); }}
  .conds {{
    display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap;
  }}
  .cond {{
    font-size: 0.76rem; padding: 3px 7px; border-radius: 6px;
    background: var(--watch-bg); color: var(--muted);
  }}
  .cond.pass {{ background: #ecfdf5; color: #059669; }}
  .score {{ font-size: 0.8rem; color: var(--muted); margin-top: 8px; }}
  .score b {{ color: var(--text); }}
  .notes {{ margin-top: 8px; font-size: 0.82rem; color: var(--text); }}
  .empty {{
    text-align: center; color: var(--muted); padding: 40px 16px;
  }}
  .history {{
    max-width: 900px; margin: 24px auto 0; padding: 0 16px;
    font-size: 0.85rem; color: var(--muted);
  }}
  .history a {{ color: var(--good); text-decoration: none; margin-right: 10px; }}
  footer {{
    max-width: 900px; margin: 24px auto 40px; padding: 0 16px;
    font-size: 0.78rem; color: var(--muted);
  }}
  .nav {{ margin-top: 8px; font-size: 0.9rem; }}
  .nav a {{ color: var(--good); text-decoration: none; font-weight: 600; }}
  .side-long {{ background: var(--fire-bg); color: var(--fire); }}
  .side-short {{ background: #ecfdf5; color: #16a34a; }}
  .levels {{
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px 8px;
    margin-top: 10px; font-size: 0.8rem; color: var(--muted);
  }}
  .levels b {{ color: var(--text); font-weight: 600; }}
  .stats {{ margin-top: 6px; font-size: 0.8rem; color: var(--muted); }}
  .card {{ position: relative; }}
  .wl-wrap {{ position: relative; display: flex; justify-content: flex-end; margin-top: 10px; }}
  .wl-btn, .wl-small, .wl-tab {{
    font: inherit; font-size: 0.8rem; cursor: pointer; border-radius: 999px;
    border: 1px solid var(--border); background: var(--card-bg); color: var(--text); padding: 4px 12px;
  }}
  .wl-btn.wl-on {{ color: #b45309; border-color: #f59e0b; background: #fffbeb; }}
  .wl-small:disabled, .wl-tab:disabled {{ opacity: 0.45; cursor: not-allowed; }}
  .wl-danger {{ color: var(--fire); }}
  .wl-menu {{
    position: absolute; right: 0; top: 100%; margin-top: 4px; z-index: 10; min-width: 200px;
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px;
    box-shadow: 0 6px 20px rgba(0,0,0,0.15); padding: 6px;
  }}
  .wl-menu-title {{ font-size: 0.75rem; color: var(--muted); padding: 4px 8px; }}
  .wl-menu-item {{
    display: block; width: 100%; text-align: left; font: inherit; font-size: 0.88rem;
    background: none; border: 0; color: var(--text); padding: 8px; border-radius: 6px; cursor: pointer;
  }}
  .wl-menu-item:hover {{ background: var(--watch-bg); }}
  .wl-menu-link {{ display: block; font-size: 0.8rem; padding: 6px 8px; color: var(--good); text-decoration: none; }}
  .wl-tabs {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .wl-tab.active {{ background: var(--good); border-color: var(--good); color: #fff; font-weight: 600; }}
  .wl-tab-add {{ border-style: dashed; color: var(--good); }}
  .wl-hint {{ font-size: 0.78rem; color: var(--muted); margin: 6px 0; min-height: 1em; }}
  .wl-bar {{ display: flex; gap: 8px; margin: 10px 0; }}
  .wl-add {{ display: flex; gap: 8px; margin-top: 6px; }}
  .wl-add input, .wl-io-box {{
    flex: 1; min-width: 0; font: inherit; font-size: 0.9rem; padding: 6px 10px;
    border: 1px solid var(--border); border-radius: 8px; background: var(--card-bg); color: var(--text);
  }}
  .wl-io-box {{ display: block; width: 100%; margin-top: 8px; font-size: 0.75rem; }}
  .wl-io {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
  .wl-remove {{ margin-top: 10px; }}
  [hidden] {{ display: none !important; }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #111318; --card-bg: #1a1d23; --text: #e5e7eb; --muted: #9ca3af;
      --border: #2b2f38; --fire-bg: #3a1a1a; --good-bg: #16233d; --watch-bg: #23262e;
    }}
    .disclaimer {{ background: #2a2210; border-color: #4a3b12; color: #fbbf24; }}
    .wl-btn.wl-on {{ background: #2a2210; border-color: #b45309; color: #fbbf24; }}
  }}
</style>"""

PAGE_TEMPLATE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>每日收盤後選股 {date_display}</title>
""" + BASE_CSS + """
</head>
<body>
<header>
  <h1>每日收盤後選股</h1>
  <div class="subtitle">資料日期：{date_display}　｜　模擬掃描 {scanned} 檔，符合門檻(達成≥{min_checklist}項) {matched} 檔</div>
  <div class="nav"><a href="{daytrade_href}">⚡ 看隔日當沖候選名單 →</a>　<a href="{asset_prefix}watchlist.html">⭐ 我的關注</a></div>
</header>
<div class="disclaimer">
  這份名單是把你自訂的技術面／籌碼面規則機械化跑一遍，用來縮小觀察範圍，<b>不是投資建議</b>，
  出現在名單上不代表會漲、沒出現也不代表不會漲，交易決策與風險仍需自行判斷。
</div>
<main>
{content}
</main>
<div class="history">
  歷史紀錄：{history_links}
</div>
<footer>
  由 stock-screener 自動產生（GitHub Actions 排程執行）。權重：月線30 ＞ 籌碼25 ＞ 成交量20 ＞ KD10≈動能10 ＞ 布林5，融資暴增扣分。
</footer>
<script src="{asset_prefix}watchlist.js" data-wl-href="{asset_prefix}watchlist.html"></script>
</body>
</html>
"""

CARD_TEMPLATE = """
<div class="card" data-code="{code}">
  <div class="card-top">
    <div>
      <div class="name">{name}</div>
      <div class="code">{code}　{market}</div>
    </div>
    <div class="price">
      <div class="close">{close:.2f}</div>
      <div class="{change_class}">{change_sign}{change_pct:.2f}%</div>
    </div>
  </div>
  <span class="badge {tier_class}">{tier}（{count}/{total}）</span>
  <div class="conds">{cond_html}</div>
  <div class="score">加權分數：<b>{score:.1f}</b> / 100</div>
  <div class="notes">{notes}</div>
</div>
"""


def _cond_html(r):
    parts = []
    for key, label in COND_LABELS:
        ok = r.get(key)
        cls = "cond pass" if ok else "cond"
        mark = "✓" if ok else "✕"
        parts.append(f'<span class="{cls}">{label} {mark}</span>')
    return "".join(parts)


def _render_card(r):
    change_pct = r.get("change_pct", 0.0)
    change_class = "change-up" if change_pct >= 0 else "change-down"
    change_sign = "+" if change_pct >= 0 else ""
    tier_class = TIER_CLASS.get(r["tier"], "tier-watch")
    notes = html_lib.escape(r.get("notes", "")) or "（無特別備註）"
    return CARD_TEMPLATE.format(
        name=html_lib.escape(r["name"]),
        code=html_lib.escape(r["code"]),
        market=html_lib.escape(r.get("market", "")),
        close=r["close"],
        change_class=change_class,
        change_sign=change_sign,
        change_pct=change_pct,
        tier_class=tier_class,
        tier=html_lib.escape(r["tier"]),
        count=r["checklist_count"],
        total=TOTAL_CONDITIONS,
        cond_html=_cond_html(r),
        score=r["score"],
        notes=notes,
    )


def render_report_html(results, target_date: str, scanned_count: int, min_checklist: int,
                        history_dates=None, is_index=True):
    """results: 已經是 run_screen() 回傳、且已用 min_checklist 篩過的清單（由高到低排序）。"""
    date_display = f"{target_date[0:4]}-{target_date[4:6]}-{target_date[6:8]}"

    if results:
        content = '<div class="grid">' + "".join(_render_card(r) for r in results) + "</div>"
    else:
        content = '<div class="empty">今天沒有股票符合門檻，明天再來看看。</div>'

    history_dates = history_dates or []
    if history_dates:
        links = " ".join(
            f'<a href="{"reports/" if is_index else ""}{d}.html">{d[0:4]}-{d[4:6]}-{d[6:8]}</a>'
            for d in history_dates
        )
    else:
        links = "（目前還沒有歷史紀錄）"

    return PAGE_TEMPLATE.format(
        date_display=date_display,
        scanned=scanned_count,
        min_checklist=min_checklist,
        matched=len(results),
        content=content,
        history_links=links,
        daytrade_href="daytrade.html" if is_index else f"../daytrade/{target_date}.html",
        asset_prefix="" if is_index else "../",
    )


def write_reports(results, target_date: str, scanned_count: int, min_checklist: int,
                   docs_dir: str):
    """寫兩份檔案：
    - docs/index.html          永遠是「最新一天」的報表（GitHub Pages 首頁固定網址）
    - docs/reports/{date}.html 當天的存檔（用來累積歷史紀錄，首頁下方會列出連結）
    """
    reports_dir = os.path.join(docs_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    # 掃描已經存在的歷史報表檔名，加上今天，取最近 30 天顯示連結（新到舊）
    existing = []
    if os.path.isdir(reports_dir):
        for fn in os.listdir(reports_dir):
            if fn.endswith(".html"):
                existing.append(fn[:-5])
    if target_date not in existing:
        existing.append(target_date)
    existing.sort(reverse=True)
    history_dates = existing[:30]

    with open(os.path.join(docs_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_report_html(results, target_date, scanned_count, min_checklist, history_dates))
    with open(os.path.join(reports_dir, f"{target_date}.html"), "w", encoding="utf-8") as f:
        f.write(render_report_html(results, target_date, scanned_count, min_checklist, history_dates,
                                   is_index=False))


# =====================================================================
# ⚡ 當沖候選名單頁面（docs/daytrade.html + docs/daytrade/{date}.html）
# =====================================================================

DT_COND_LABELS = [
    ("condA_volatility", "A波動"),
    ("condB_liquidity", "B流動性"),
    ("condC_volume", "C量能"),
    ("condD_close", "D收盤"),
    ("condE_trend", "E順勢"),
    ("condF_chips", "F法人"),
]

DT_PAGE_TEMPLATE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>隔日當沖候選 {date_display}</title>
""" + BASE_CSS + """
</head>
<body>
<header>
  <h1>⚡ 隔日當沖候選名單</h1>
  <div class="subtitle">資料日期：{date_display}（給下一個交易日盤前參考）　｜　通過流動性濾網 {scanned} 檔，
    分數≥{min_score} 列出 {matched} 檔（偏多 {n_long}／偏空 {n_short}）{list_note}</div>
  <div class="nav"><a href="{swing_href}">← 回波段選股名單</a>　<a href="{asset_prefix}watchlist.html">⭐ 我的關注</a></div>
</header>
<div class="disclaimer">
  只用<b>日K資料</b>挑「明天值得盯盤」的股票：流動性夠、波動夠、有人氣、方向清楚。看不到盤中分時與開盤跳空，
  <b>不是進出場建議</b>。參考價位只是讓你盤前先標好關鍵價，實際進場請看開盤後量價，並嚴守停損。
  當沖失敗要自行負擔價差、手續費與證交稅，也可能因違約交割產生法律責任，請先確認已開通當沖資格與額度。
</div>
<main>
{content}
</main>
<div class="history">
  歷史紀錄：{history_links}
</div>
<footer>
  權重：波動25 ＋ 流動性20 ＋ 量能20 ＋ 收盤強弱15 ＋ 順勢10 ＋ 法人10，漲跌停附近扣分。
  Pivot=(高+低+收)/3，R1=2P−低，S1=2P−高；參考停損＝ATR×倍數（可在 config.py 調整）。
</footer>
<script src="{asset_prefix}watchlist.js" data-wl-href="{asset_prefix}watchlist.html"></script>
</body>
</html>
"""

DT_CARD_TEMPLATE = """
<div class="card" data-code="{code}">
  <div class="card-top">
    <div>
      <div class="name">{name}</div>
      <div class="code">{code}　{market}</div>
    </div>
    <div class="price">
      <div class="close">{close:.2f}</div>
      <div class="{change_class}">{change_sign}{change_pct:.2f}%</div>
    </div>
  </div>
  <span class="badge {side_class}">偏{side}　{score:.1f} 分</span>
  <div class="conds">{cond_html}</div>
  <div class="stats">成交 {volume_lots:,} 張／{turnover_e8:.1f} 億　｜　ATR {atr_pct:.1f}%　｜　量比 {vol_ratio:.1f}x{dt_ratio}</div>
  <div class="levels">
    <div>今日高 <b>{high:.2f}</b></div><div>Pivot <b>{pivot:.2f}</b></div><div>R1 <b>{r1:.2f}</b></div>
    <div>今日低 <b>{low:.2f}</b></div><div>ATR <b>{atr:.2f}</b></div><div>S1 <b>{s1:.2f}</b></div>
  </div>
  <div class="stats">參考停損距離：約 <b>{stop_dist:.2f}</b> 元（{side_hint}）</div>
  <div class="notes">{notes}</div>
</div>
"""


def _render_dt_card(r):
    change_pct = r["change_pct"]
    long_side = r["side"] == "多"
    parts = []
    for key, label in DT_COND_LABELS:
        ok = r.get(key)
        parts.append(f'<span class="{"cond pass" if ok else "cond"}">{label} {"✓" if ok else "✕"}</span>')
    dt_ratio = f"　｜　當沖率 {r['daytrade_ratio']:.0f}%" if r.get("daytrade_ratio") is not None else ""
    side_hint = ("站上今日高/R1 再考慮做多，跌破進場價減此距離停損" if long_side
                 else "跌破今日低/S1 再考慮做空，漲過進場價加此距離停損")
    return DT_CARD_TEMPLATE.format(
        name=html_lib.escape(r["name"]),
        code=html_lib.escape(r["code"]),
        market=html_lib.escape(r.get("market", "")),
        close=r["close"],
        change_class="change-up" if change_pct >= 0 else "change-down",
        change_sign="+" if change_pct >= 0 else "",
        change_pct=change_pct,
        side=r["side"],
        side_class="side-long" if long_side else "side-short",
        score=r["score"],
        cond_html="".join(parts),
        volume_lots=r["volume_lots"],
        turnover_e8=r["turnover_e8"],
        atr_pct=r["atr_pct"],
        vol_ratio=r["vol_ratio"],
        dt_ratio=dt_ratio,
        high=r["high"], low=r["low"], pivot=r["pivot"], r1=r["r1"], s1=r["s1"],
        atr=r["atr"], stop_dist=r["stop_dist"], side_hint=side_hint,
        notes=html_lib.escape(r.get("notes", "")) or "（無特別備註）",
    )


def render_daytrade_html(results, target_date: str, scanned_count: int, min_score: float,
                         list_applied: bool, history_dates=None, is_index=True):
    date_display = f"{target_date[0:4]}-{target_date[4:6]}-{target_date[6:8]}"
    if results:
        content = '<div class="grid">' + "".join(_render_dt_card(r) for r in results) + "</div>"
    else:
        content = '<div class="empty">今天沒有股票符合當沖候選門檻。</div>'

    history_dates = history_dates or []
    if history_dates:
        prefix = "daytrade/" if is_index else ""
        links = " ".join(
            f'<a href="{prefix}{d}.html">{d[0:4]}-{d[4:6]}-{d[6:8]}</a>' for d in history_dates
        )
    else:
        links = "（目前還沒有歷史紀錄）"

    n_long = sum(1 for r in results if r["side"] == "多")
    return DT_PAGE_TEMPLATE.format(
        date_display=date_display,
        scanned=scanned_count,
        min_score=min_score,
        matched=len(results),
        n_long=n_long,
        n_short=len(results) - n_long,
        list_note="" if list_applied else "　｜　⚠️本次未取得官方可當沖清單，請自行確認標的可當沖",
        swing_href="index.html" if is_index else f"../reports/{target_date}.html",
        asset_prefix="" if is_index else "../",
        content=content,
        history_links=links,
    )


def write_daytrade_reports(results, target_date: str, scanned_count: int, min_score: float,
                           list_applied: bool, docs_dir: str):
    """docs/daytrade.html 永遠是最新一天；docs/daytrade/{date}.html 是當天存檔。"""
    archive_dir = os.path.join(docs_dir, "daytrade")
    os.makedirs(archive_dir, exist_ok=True)
    existing = [fn[:-5] for fn in os.listdir(archive_dir) if fn.endswith(".html")]
    if target_date not in existing:
        existing.append(target_date)
    history_dates = sorted(existing, reverse=True)[:30]

    args = (results, target_date, scanned_count, min_score, list_applied, history_dates)
    with open(os.path.join(docs_dir, "daytrade.html"), "w", encoding="utf-8") as f:
        f.write(render_daytrade_html(*args))
    with open(os.path.join(archive_dir, f"{target_date}.html"), "w", encoding="utf-8") as f:
        f.write(render_daytrade_html(*args, is_index=False))


# =====================================================================
# ⭐ 我的關注（docs/watchlist.html）
# =====================================================================
# 選單本身存在瀏覽器（見 docs/watchlist.js），這裡只負責把「當天所有股票的收盤、漲跌，
# 以及有沒有進波段／當沖名單」內嵌進頁面，讓關注清單打開就看得到最新狀況。

WL_PAGE_TEMPLATE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>我的關注 {date_display}</title>
""" + BASE_CSS + """
</head>
<body>
<header>
  <h1>⭐ 我的關注</h1>
  <div class="subtitle">資料日期：{date_display}　｜　自設選單最多 5 個，可以改名</div>
  <div class="nav"><a href="index.html">← 波段選股</a>　<a href="daytrade.html">⚡ 當沖名單</a></div>
</header>
<div class="disclaimer">
  選單存在<b>這支手機／這台電腦的瀏覽器</b>裡，不同裝置、不同瀏覽器各自一份；清除瀏覽器資料會一起清掉。
  換裝置或想備份，用最下面的「匯出選單／匯入選單」搬過去。
</div>
<main>
  <div id="wl-root"><div class="empty">載入中…（需要開啟 JavaScript）</div></div>
</main>
<div class="history">
  <div class="wl-io" id="wl-io"></div>
</div>
<footer>
  價格與「是否在名單上」是每天收盤後自動更新的資料；不在波段／當沖名單上不代表不能買賣，只是當天沒有符合那套條件。
</footer>
<script type="application/json" id="wl-data">{data_json}</script>
<script src="watchlist.js"></script>
</body>
</html>
"""


def build_watchlist_snapshot(target_date, day_prices, swing_results=None, daytrade_results=None):
    """day_prices: [(code, name, close, change)]；回傳內嵌在關注頁的精簡資料。"""
    stocks = {}
    for code, name, close, change in day_prices:
        prev = (close or 0) - (change or 0)
        stocks[code] = {
            "n": name,
            "c": round(close or 0.0, 2),
            "p": round((change or 0) / prev * 100, 2) if prev else 0.0,
        }
    for r in swing_results or []:
        if r["code"] in stocks:
            stocks[r["code"]]["s"] = f"{r['tier']} {r['checklist_count']}/{TOTAL_CONDITIONS}・{r['score']:.1f}分"
    for r in daytrade_results or []:
        if r["code"] in stocks:
            stocks[r["code"]]["d"] = f"偏{r['side']}・{r['score']:.1f}分"
    return {"date": target_date, "stocks": stocks}


def write_watchlist_page(snapshot, docs_dir: str):
    import json
    d = snapshot["date"]
    data_json = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    data_json = data_json.replace("</", "<\\/")  # 避免股票名稱裡出現 </script> 之類的字串把頁面截斷
    with open(os.path.join(docs_dir, "watchlist.html"), "w", encoding="utf-8") as f:
        f.write(WL_PAGE_TEMPLATE.format(date_display=f"{d[0:4]}-{d[4:6]}-{d[6:8]}", data_json=data_json))
