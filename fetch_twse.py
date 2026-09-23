# -*- coding: utf-8 -*-
"""
上市 (TWSE) 資料抓取
====================
資料來源（皆為 TWSE 官方公開 JSON，非會員制、不需金鑰）：
  - 每日收盤行情(全部)：https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX
  - 三大法人買賣超日報：https://www.twse.com.tw/rwd/zh/fund/T86
  - 融資融券餘額：      https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN
  - 當日沖銷交易標的：  https://www.twse.com.tw/rwd/zh/afterTrading/TWTB4U（當沖選股用，未經實測，見下方說明）

三個接口都支援用 date=YYYYMMDD 查「特定歷史日期」的全市場資料（一次拿全部股票，
不用一檔一檔抓），所以回補歷史只需要「交易日數」次請求，而不是「股票數 x 天數」次。
"""

from datetime import datetime

from fetch_common import get_json, to_float
from tradedays import to_yyyymmdd, candidate_dates
import db
from config import BACKFILL_TRADING_DAYS

MARKET = "TWSE"

MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
MI_MARGN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
TWTB4U_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/TWTB4U"


def _fetch_prices(date_str: str):
    data = get_json(MI_INDEX_URL, {"date": date_str, "type": "ALLBUT0999", "response": "json"})
    if not data or data.get("stat") != "OK":
        return []
    tables = data.get("tables") or []
    target = None
    for t in tables:
        fields = t.get("fields") or []
        if "證券代號" in fields and "收盤價" in fields and "成交股數" in fields:
            target = t
            break
    if target is None:
        return []

    fields = target["fields"]
    idx = {name: i for i, name in enumerate(fields)}
    rows = []
    for row in target.get("data", []):
        try:
            code = row[idx["證券代號"]].strip()
            name = row[idx["證券名稱"]].strip()
            close = to_float(row[idx["收盤價"]], default=None)
            if close is None or close == 0.0:
                continue  # 當日無成交
            change_dir_html = row[idx["漲跌(+/-)"]] or ""
            change_val = to_float(row[idx["漲跌價差"]])
            # 欄位內容是一段 HTML，例如 "<p style= color:red>+</p>"（紅漲）或 "...>-</p>"（綠跌）
            if ">-<" in change_dir_html or change_dir_html.strip().endswith("-</p>"):
                sign = -1.0
            else:
                sign = 1.0
            rows.append({
                "date": date_str,
                "market": MARKET,
                "code": code,
                "name": name,
                "open": to_float(row[idx["開盤價"]]),
                "high": to_float(row[idx["最高價"]]),
                "low": to_float(row[idx["最低價"]]),
                "close": close,
                "volume": to_float(row[idx["成交股數"]]),
                "change": sign * change_val,
            })
        except (KeyError, IndexError, AttributeError):
            continue
    return rows


def _fetch_institutional(date_str: str):
    data = get_json(T86_URL, {"date": date_str, "selectType": "ALL", "response": "json"})
    if not data or data.get("stat") != "OK":
        return []
    fields = data.get("fields") or []
    idx = {name: i for i, name in enumerate(fields)}
    rows = []
    for row in data.get("data", []):
        try:
            code = row[idx["證券代號"]].strip()
            foreign_net = to_float(row[idx["外陸資買賣超股數(不含外資自營商)"]]) + \
                to_float(row[idx["外資自營商買賣超股數"]])
            trust_net = to_float(row[idx["投信買賣超股數"]])
            dealer_net = to_float(row[idx["自營商買賣超股數"]])
            total_net = to_float(row[idx["三大法人買賣超股數"]])
            rows.append({
                "date": date_str,
                "market": MARKET,
                "code": code,
                "foreign_net": foreign_net,
                "trust_net": trust_net,
                "dealer_net": dealer_net,
                "total_net": total_net,
            })
        except (KeyError, IndexError, AttributeError):
            continue
    return rows


def _fetch_margin(date_str: str):
    data = get_json(MI_MARGN_URL, {"date": date_str, "selectType": "ALL", "response": "json"})
    if not data or data.get("stat") != "OK":
        return []
    # 舊格式個股資料放在最外層 data；新版 rwd 接口改放在 tables 裡（第一張是「信用交易統計」總表，
    # 個股明細是欄位含「代號」的那張）。兩種都支援，欄位順序相同：代號,名稱,融資買進,融資賣出,現金償還,前日餘額,今日餘額...
    detail = data.get("data") or []
    if not detail:
        for t in data.get("tables") or []:
            fields = t.get("fields") or []
            if fields and "代號" in fields[0] and len(fields) >= 7:
                detail = t.get("data") or []
                break
    rows = []
    for row in detail:
        try:
            code = row[0].strip()
            rows.append({
                "date": date_str,
                "market": MARKET,
                "code": code,
                "margin_buy": to_float(row[2]),
                "margin_sell": to_float(row[3]),
                "margin_balance": to_float(row[6]),
            })
        except (KeyError, IndexError, AttributeError):
            continue
    return rows


def _find_field(fields, *keywords):
    """回傳第一個「名稱同時包含所有 keywords」的欄位索引，找不到回傳 None。"""
    for i, name in enumerate(fields):
        if all(k in name for k in keywords):
            return i
    return None


def _fetch_daytrade_list(date_str: str):
    """可當沖標的清單。這個接口在開發環境連不到、沒辦法實測，所以不寫死欄位位置，
    而是在回應裡所有表格中找「有證券代號 + 當沖註記」欄位的那一張，用欄位名稱比對；
    格式對不上就回傳空 list（呼叫端會當作「不知道」而不套用濾網，不會誤殺整個名單）。"""
    data = get_json(TWTB4U_URL, {"date": date_str, "response": "json"})
    if not data or data.get("stat") != "OK":
        return []
    candidates = list(data.get("tables") or [])
    if data.get("fields"):
        candidates.append({"fields": data["fields"], "data": data.get("data", [])})

    for t in candidates:
        fields = t.get("fields") or []
        i_code = _find_field(fields, "證券代號")
        i_flag = _find_field(fields, "註記")
        if i_code is None or i_flag is None:
            continue
        i_vol = _find_field(fields, "成交股數")
        rows = []
        for row in t.get("data", []):
            try:
                code = str(row[i_code]).strip()
                if not code:
                    continue
                rows.append({
                    "date": date_str,
                    "market": MARKET,
                    "code": code,
                    "sell_first_suspended": 1 if str(row[i_flag]).strip() not in ("", "-") else 0,
                    "daytrade_volume": to_float(row[i_vol]) if i_vol is not None else None,
                })
            except (IndexError, AttributeError):
                continue
        return rows
    return []


def fetch_and_cache_daytrade(date_str: str):
    """只抓目標日期（當沖選股只需要當天這份清單，不用回補歷史）。已有資料就不重抓；
    抓不到不會寫入任何紀錄，下次執行會再試。回傳該日清單檔數。"""
    existing = db.get_daytrade_list(MARKET, date_str)
    if existing:
        return len(existing)
    rows = _fetch_daytrade_list(date_str)
    db.save_daytrade_list(rows)
    if rows:
        print(f"  [TWSE] {date_str} 可當沖標的 {len(rows)} 檔")
    else:
        print(f"  [TWSE] {date_str} 可當沖標的清單抓不到或格式不符，本次不套用可當沖濾網")
    return len(rows)


def test_daytrade(date_str: str):
    """印出 TWTB4U 原始回應的結構，確認欄位名稱/格式。"""
    data = get_json(TWTB4U_URL, {"date": date_str, "response": "json"})
    if not data:
        print("抓不到資料（網路問題或官網沒回應）")
        return
    print("stat =", data.get("stat"))
    for i, t in enumerate(data.get("tables") or []):
        print(f"tables[{i}] title={t.get('title')!r}")
        print("   fields =", t.get("fields"))
        print("   data[:3] =", (t.get("data") or [])[:3])
    if data.get("fields"):
        print("top-level fields =", data.get("fields"))
        print("top-level data[:3] =", (data.get("data") or [])[:3])
    rows = _fetch_daytrade_list(date_str)
    print(f"\n解析結果：{len(rows)} 檔，前5筆：")
    for r in rows[:5]:
        print("  ", r)


def fetch_and_cache_range(end_date: datetime, n_days: int = BACKFILL_TRADING_DAYS):
    """回補從 end_date 往前 n_days 個「可能交易日」的三種資料，已存在快取的日期會跳過。"""
    dates = candidate_dates(end_date, n_days)
    fetched_trading_days = 0
    for d in dates:
        date_str = to_yyyymmdd(d)

        if not db.already_fetched(MARKET, "prices", date_str):
            rows = _fetch_prices(date_str)
            status = "OK" if rows else "EMPTY"
            db.save_prices(rows)
            db.mark_fetched(MARKET, "prices", date_str, status)
            if rows:
                fetched_trading_days += 1
                print(f"  [TWSE] {date_str} 收盤價 {len(rows)} 檔")

        # 只保留當天有收盤價的股票：T86 另外含一萬多檔權證，選股用不到，卻會讓快取檔爆掉 GitHub 100MB 上限
        stock_codes = {c for c, _ in db.list_codes_with_price_on(MARKET, date_str)}

        if not db.already_fetched(MARKET, "institutional", date_str):
            rows = _fetch_institutional(date_str)
            if stock_codes:
                rows = [r for r in rows if r["code"] in stock_codes]
            status = "OK" if rows else "EMPTY"
            db.save_institutional(rows)
            db.mark_fetched(MARKET, "institutional", date_str, status)
            if rows:
                print(f"  [TWSE] {date_str} 三大法人 {len(rows)} 檔")

        # 融資：早期解析格式不符，交易日也被記成 EMPTY，這裡讓「有收盤價卻沒融資」的日子重抓一次；
        # 重抓還是空的就記成 NODATA，之後不再重試，避免每天白打幾十次請求
        margin_status = db.fetch_status(MARKET, "margin", date_str)
        if margin_status is None or (margin_status == "EMPTY" and stock_codes):
            rows = _fetch_margin(date_str)
            status = "OK" if rows else ("EMPTY" if margin_status is None else "NODATA")
            db.save_margin(rows)
            db.mark_fetched(MARKET, "margin", date_str, status)
            if rows:
                print(f"  [TWSE] {date_str} 融資融券 {len(rows)} 檔")

    return fetched_trading_days
