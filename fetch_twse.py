# -*- coding: utf-8 -*-
"""
上市 (TWSE) 資料抓取
====================
資料來源（皆為 TWSE 官方公開 JSON，非會員制、不需金鑰）：
  - 每日收盤行情(全部)：https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX
  - 三大法人買賣超日報：https://www.twse.com.tw/rwd/zh/fund/T86
  - 融資融券餘額：      https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN

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
    rows = []
    for row in data.get("data", []):
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

        if not db.already_fetched(MARKET, "institutional", date_str):
            rows = _fetch_institutional(date_str)
            status = "OK" if rows else "EMPTY"
            db.save_institutional(rows)
            db.mark_fetched(MARKET, "institutional", date_str, status)
            if rows:
                print(f"  [TWSE] {date_str} 三大法人 {len(rows)} 檔")

        if not db.already_fetched(MARKET, "margin", date_str):
            rows = _fetch_margin(date_str)
            status = "OK" if rows else "EMPTY"
            db.save_margin(rows)
            db.mark_fetched(MARKET, "margin", date_str, status)
            if rows:
                print(f"  [TWSE] {date_str} 融資融券 {len(rows)} 檔")

    return fetched_trading_days
