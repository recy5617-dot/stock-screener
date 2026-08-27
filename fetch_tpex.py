# -*- coding: utf-8 -*-
"""
上櫃 (TPEX) 資料抓取 —— 【實驗性 / 未在本次開發環境完整驗證】
================================================================
開發這支程式的環境對 tpex.org.tw 網域有網路層封鎖（連 API 文件頁都無法連線），
所以下面的三個端點是依據 TPEX 官方公開 API 長年慣用的路徑與參數格式撰寫，
「邏輯與 TWSE 版本一致」，但無法在本環境實際跑一次驗證欄位順序是否仍正確。

使用前請先執行：
    python main.py --test-tpex
會只抓「今天」一天的資料印出前 3 筆，方便你確認欄位是否對得上。
如果發現抓不到 / 欄位錯位，最快的作法是打開瀏覽器開發者工具（F12 -> Network），
到 https://www.tpex.org.tw 查一下「上櫃個股日成交資訊」頁面實際打的 API 網址，
對照本檔案的 URL 與欄位索引修正即可（架構完全比照 fetch_twse.py）。

如果你只需要上市股票，可以直接在 config.py 把 MARKETS 改成 ["TWSE"] 略過這個模組。
"""

from datetime import datetime

from fetch_common import get_json, to_float
from tradedays import to_roc_slash, candidate_dates
import db
from config import BACKFILL_TRADING_DAYS

MARKET = "TPEX"

# 上櫃股票每日收盤行情（全部）
QUOTES_URL = "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php"
# 上櫃三大法人買賣超日報
INSTI_URL = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
# 上櫃融資融券餘額
MARGIN_URL = "https://www.tpex.org.tw/web/stock/margin_trading/margin_bal/margin_bal_result.php"

REFERER = "https://www.tpex.org.tw/"


def _extract_table(data):
    """TPEX 舊式 CGI JSON 常見兩種殼："aaData" 或 "tables"[0]["data"]，兩種都試著解析。"""
    if not data:
        return None
    if isinstance(data, dict):
        if "aaData" in data and data["aaData"]:
            return data["aaData"]
        tables = data.get("tables")
        if tables:
            for t in tables:
                if t.get("data"):
                    return t["data"]
    return None


def _fetch_prices(date_str_roc: str, date_str_std: str):
    data = get_json(QUOTES_URL, {"l": "zh-tw", "d": date_str_roc, "se": "EW"}, referer=REFERER)
    rows_raw = _extract_table(data)
    if not rows_raw:
        return []
    rows = []
    for row in rows_raw:
        try:
            code = str(row[0]).strip()
            name = str(row[1]).strip()
            close = to_float(row[2], default=None)
            if not code or close is None or close == 0.0:
                continue
            change_val = to_float(row[3])
            open_ = to_float(row[4])
            high = to_float(row[5])
            low = to_float(row[6])
            volume = to_float(row[7])  # 成交股數（部分版本此欄是成交仟股，如發現數量差1000倍請調整）
            rows.append({
                "date": date_str_std,
                "market": MARKET,
                "code": code,
                "name": name,
                "open": open_, "high": high, "low": low, "close": close,
                "volume": volume,
                "change": change_val,
            })
        except (IndexError, ValueError, TypeError):
            continue
    return rows


def _fetch_institutional(date_str_roc: str, date_str_std: str):
    data = get_json(INSTI_URL, {"l": "zh-tw", "d": date_str_roc, "se": "EW", "t": "D"}, referer=REFERER)
    rows_raw = _extract_table(data)
    if not rows_raw:
        return []
    rows = []
    for row in rows_raw:
        try:
            code = str(row[0]).strip()
            if not code:
                continue
            # 欄位順序比照 TWSE T86：外資合計淨額, 投信淨額, 自營淨額, 三大法人合計淨額
            # 實際欄數請以 --test-tpex 印出結果核對，此為預設猜測位置
            foreign_net = to_float(row[4]) if len(row) > 4 else 0.0
            trust_net = to_float(row[7]) if len(row) > 7 else 0.0
            dealer_net = to_float(row[10]) if len(row) > 10 else 0.0
            total_net = to_float(row[-1])
            rows.append({
                "date": date_str_std,
                "market": MARKET,
                "code": code,
                "foreign_net": foreign_net,
                "trust_net": trust_net,
                "dealer_net": dealer_net,
                "total_net": total_net,
            })
        except (IndexError, ValueError, TypeError):
            continue
    return rows


def _fetch_margin(date_str_roc: str, date_str_std: str):
    data = get_json(MARGIN_URL, {"l": "zh-tw", "d": date_str_roc, "se": "EW"}, referer=REFERER)
    rows_raw = _extract_table(data)
    if not rows_raw:
        return []
    rows = []
    for row in rows_raw:
        try:
            code = str(row[0]).strip()
            if not code:
                continue
            rows.append({
                "date": date_str_std,
                "market": MARKET,
                "code": code,
                "margin_buy": to_float(row[2]) if len(row) > 2 else 0.0,
                "margin_sell": to_float(row[3]) if len(row) > 3 else 0.0,
                "margin_balance": to_float(row[6]) if len(row) > 6 else 0.0,
            })
        except (IndexError, ValueError, TypeError):
            continue
    return rows


def fetch_and_cache_range(end_date: datetime, n_days: int = BACKFILL_TRADING_DAYS):
    from tradedays import to_yyyymmdd

    dates = candidate_dates(end_date, n_days)
    fetched_trading_days = 0
    for d in dates:
        date_std = to_yyyymmdd(d)
        date_roc = to_roc_slash(d)

        try:
            if not db.already_fetched(MARKET, "prices", date_std):
                rows = _fetch_prices(date_roc, date_std)
                db.save_prices(rows)
                db.mark_fetched(MARKET, "prices", date_std, "OK" if rows else "EMPTY")
                if rows:
                    fetched_trading_days += 1
                    print(f"  [TPEX] {date_std} 收盤價 {len(rows)} 檔")

            if not db.already_fetched(MARKET, "institutional", date_std):
                rows = _fetch_institutional(date_roc, date_std)
                db.save_institutional(rows)
                db.mark_fetched(MARKET, "institutional", date_std, "OK" if rows else "EMPTY")
                if rows:
                    print(f"  [TPEX] {date_std} 三大法人 {len(rows)} 檔")

            if not db.already_fetched(MARKET, "margin", date_std):
                rows = _fetch_margin(date_roc, date_std)
                db.save_margin(rows)
                db.mark_fetched(MARKET, "margin", date_std, "OK" if rows else "EMPTY")
                if rows:
                    print(f"  [TPEX] {date_std} 融資融券 {len(rows)} 檔")
        except Exception as e:  # noqa: BLE001
            print(f"  [TPEX 警告] {date_std} 抓取發生例外，略過：{e}")
            continue

    return fetched_trading_days


def test_today():
    """--test-tpex 用：只抓今天，印出前 3 筆原始資料方便核對欄位。"""
    today = datetime.now()
    date_roc = to_roc_slash(today)
    print(f"測試 TPEX 資料（{date_roc}）...")
    data = get_json(QUOTES_URL, {"l": "zh-tw", "d": date_roc, "se": "EW"}, referer=REFERER)
    print("原始回應片段：", str(data)[:1000])
