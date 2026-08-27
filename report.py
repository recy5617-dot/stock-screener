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
]

PAGE_TEMPLATE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>每日收盤後選股 {date_display}</title>
<style>
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
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #111318; --card-bg: #1a1d23; --text: #e5e7eb; --muted: #9ca3af;
      --border: #2b2f38; --fire-bg: #3a1a1a; --good-bg: #16233d; --watch-bg: #23262e;
    }}
    .disclaimer {{ background: #2a2210; border-color: #4a3b12; color: #fbbf24; }}
  }}
</style>
</head>
<body>
<header>
  <h1>每日收盤後選股</h1>
  <div class="subtitle">資料日期：{date_display}　｜　模擬掃描 {scanned} 檔，符合門檻(達成≥{min_checklist}項) {matched} 檔</div>
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
  由 stock-screener 自動產生（GitHub Actions 排程執行）。權重：月線35 ＞ 籌碼30 ＞ 成交量20 ＞ KD15，融資暴增扣分。
</footer>
</body>
</html>
"""

CARD_TEMPLATE = """
<div class="card">
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
  <span class="badge {tier_class}">{tier}（{count}/5）</span>
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
        cond_html=_cond_html(r),
        score=r["score"],
        notes=notes,
    )


def render_report_html(results, target_date: str, scanned_count: int, min_checklist: int,
                        history_dates=None):
    """results: 已經是 run_screen() 回傳、且已用 min_checklist 篩過的清單（由高到低排序）。"""
    date_display = f"{target_date[0:4]}-{target_date[4:6]}-{target_date[6:8]}"

    if results:
        content = '<div class="grid">' + "".join(_render_card(r) for r in results) + "</div>"
    else:
        content = '<div class="empty">今天沒有股票符合門檻，明天再來看看。</div>'

    history_dates = history_dates or []
    if history_dates:
        links = " ".join(
            f'<a href="reports/{d}.html">{d[0:4]}-{d[4:6]}-{d[6:8]}</a>' for d in history_dates
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

    html_out = render_report_html(results, target_date, scanned_count, min_checklist, history_dates)

    with open(os.path.join(docs_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_out)
    with open(os.path.join(reports_dir, f"{target_date}.html"), "w", encoding="utf-8") as f:
        f.write(html_out)
