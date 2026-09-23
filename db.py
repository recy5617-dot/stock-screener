# -*- coding: utf-8 -*-
"""
本地快取資料庫 (SQLite)
======================
每天執行只會補抓「還沒有的日期」，抓過的資料存本地，
不會每次都重新對 TWSE / TPEX 重複下載，避免浪費時間、也對官方站點比較友善。
"""

import sqlite3
from contextlib import contextmanager

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, change REAL,
    PRIMARY KEY (date, market, code)
);

CREATE TABLE IF NOT EXISTS institutional (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    code TEXT NOT NULL,
    foreign_net REAL,
    trust_net REAL,
    dealer_net REAL,
    total_net REAL,
    PRIMARY KEY (date, market, code)
);

CREATE TABLE IF NOT EXISTS margin (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    code TEXT NOT NULL,
    margin_balance REAL,
    margin_buy REAL,
    margin_sell REAL,
    PRIMARY KEY (date, market, code)
);

CREATE TABLE IF NOT EXISTS fetch_log (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    dataset TEXT NOT NULL,
    status TEXT NOT NULL,  -- OK / EMPTY(non-trading day) / ERROR
    PRIMARY KEY (date, market, dataset)
);

-- 集保股權分散表（大戶持股比例，選用功能，見 config.ENABLE_BIG_HOLDER_CHECK）
-- 這份資料一週才更新一次（通常每週五公告上週五的資料），不是每個交易日都有新資料，
-- 所以用「資料日期」而不是交易日期為主鍵，抓歷史時直接抓「目前最新一期」就好。
CREATE TABLE IF NOT EXISTS big_holder (
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    big_holder_pct REAL,
    PRIMARY KEY (date, code)
);

-- 可當沖標的清單（TWSE TWTB4U，當沖選股用，見 config.ENABLE_DAYTRADE_LIST）
-- sell_first_suspended=1 代表「暫停現股賣出後現款買進當沖」（不能先賣後買，只能做多）
CREATE TABLE IF NOT EXISTS daytrade_list (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    code TEXT NOT NULL,
    sell_first_suspended INTEGER,
    daytrade_volume REAL,
    PRIMARY KEY (date, market, code)
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    # 刻意不用 WAL 模式：這個檔案之後會被 GitHub Actions 提交回 git repo 做為每次執行的
    # 快取，WAL 模式會產生 -wal/-shm 額外檔案，資料庫的「最終狀態」不保證都寫回主檔案，
    # 用預設的 rollback journal，確保每次 commit 後 .sqlite3 這一個檔案就是完整最新狀態。
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def already_fetched(market: str, dataset: str, date: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT status FROM fetch_log WHERE date=? AND market=? AND dataset=?",
            (date, market, dataset),
        )
        row = cur.fetchone()
        return row is not None


def fetch_status(market: str, dataset: str, date: str):
    """回傳 fetch_log 裡的狀態字串（OK / EMPTY），沒抓過回傳 None。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM fetch_log WHERE date=? AND market=? AND dataset=?",
            (date, market, dataset),
        ).fetchone()
        return row[0] if row else None


def prune(keep_trading_days: int):
    """控制快取檔大小（GitHub 單檔上限 100MB）：
    1) 刪掉沒有收盤價的法人/融資資料（權證等，選股用不到）
    2) 只保留最近 keep_trading_days 個交易日，更舊的刪掉
    3) VACUUM 把空間真的還回來（SQLite 刪資料不會自動縮檔）
    回傳 (刪除筆數, 整理後檔案大小MB)。"""
    import os
    deleted = 0
    with get_conn() as conn:
        for table in ("institutional", "margin"):
            cur = conn.execute(
                f"""DELETE FROM {table} WHERE NOT EXISTS (
                        SELECT 1 FROM prices p
                        WHERE p.date={table}.date AND p.market={table}.market AND p.code={table}.code)"""
            )
            deleted += cur.rowcount
        row = conn.execute(
            "SELECT date FROM (SELECT DISTINCT date FROM prices ORDER BY date DESC LIMIT ?) ORDER BY date LIMIT 1",
            (keep_trading_days,),
        ).fetchone()
        if row:
            cutoff = row[0]
            for table in ("prices", "institutional", "margin", "daytrade_list"):
                deleted += conn.execute(f"DELETE FROM {table} WHERE date < ?", (cutoff,)).rowcount
    if deleted:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
    return deleted, os.path.getsize(DB_PATH) / 1024 / 1024


def mark_fetched(market: str, dataset: str, date: str, status: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (date, market, dataset, status) VALUES (?,?,?,?)",
            (date, market, dataset, status),
        )


def save_prices(rows):
    """rows: list of dict with keys date, market, code, name, open, high, low, close, volume, change"""
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO prices
               (date, market, code, name, open, high, low, close, volume, change)
               VALUES (:date,:market,:code,:name,:open,:high,:low,:close,:volume,:change)""",
            rows,
        )


def save_institutional(rows):
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO institutional
               (date, market, code, foreign_net, trust_net, dealer_net, total_net)
               VALUES (:date,:market,:code,:foreign_net,:trust_net,:dealer_net,:total_net)""",
            rows,
        )


def save_margin(rows):
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO margin
               (date, market, code, margin_balance, margin_buy, margin_sell)
               VALUES (:date,:market,:code,:margin_balance,:margin_buy,:margin_sell)""",
            rows,
        )


def get_price_history(market: str, code: str, up_to_date: str, limit_days: int):
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT date, open, high, low, close, volume, change FROM prices
               WHERE market=? AND code=? AND date<=?
               ORDER BY date DESC LIMIT ?""",
            (market, code, up_to_date, limit_days),
        )
        rows = cur.fetchall()
    rows.reverse()  # 由舊到新
    return rows


def get_institutional_history(market: str, code: str, up_to_date: str, limit_days: int):
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT date, foreign_net, trust_net, dealer_net, total_net FROM institutional
               WHERE market=? AND code=? AND date<=?
               ORDER BY date DESC LIMIT ?""",
            (market, code, up_to_date, limit_days),
        )
        rows = cur.fetchall()
    rows.reverse()
    return rows


def get_margin_history(market: str, code: str, up_to_date: str, limit_days: int):
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT date, margin_balance, margin_buy, margin_sell FROM margin
               WHERE market=? AND code=? AND date<=?
               ORDER BY date DESC LIMIT ?""",
            (market, code, up_to_date, limit_days),
        )
        rows = cur.fetchall()
    rows.reverse()
    return rows


def latest_price_date(up_to_date: str):
    """快取裡 <= up_to_date 的最近一個有收盤價的日期，沒有回傳 None。"""
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(date) FROM prices WHERE date<=?", (up_to_date,)).fetchone()
        return row[0] if row else None


def get_day_prices(market: str, date: str):
    """某天所有股票的 (code, name, close, change)，給關注頁顯示最新價用。"""
    with get_conn() as conn:
        return conn.execute(
            "SELECT code, name, close, change FROM prices WHERE market=? AND date=? ORDER BY code",
            (market, date),
        ).fetchall()


def list_codes_with_price_on(market: str, date: str):
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT code, name FROM prices WHERE market=? AND date=?", (market, date)
        )
        return cur.fetchall()


def save_big_holder(rows):
    """rows: list of dict with keys date, code, big_holder_pct"""
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO big_holder (date, code, big_holder_pct)
               VALUES (:date,:code,:big_holder_pct)""",
            rows,
        )


def get_big_holder_history(code: str, up_to_date: str, limit_records: int = 2):
    """回傳某檔股票「最近 limit_records 期」的大戶持股比例，由舊到新：[(date, pct), ...]。
    因為是週資料，這裡的 up_to_date 只是上限，不要求剛好等於當天。"""
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT date, big_holder_pct FROM big_holder
               WHERE code=? AND date<=?
               ORDER BY date DESC LIMIT ?""",
            (code, up_to_date, limit_records),
        )
        rows = cur.fetchall()
    rows.reverse()
    return rows


def latest_big_holder_date(up_to_date: str):
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT MAX(date) FROM big_holder WHERE date<=?", (up_to_date,)
        )
        row = cur.fetchone()
        return row[0] if row else None


def save_daytrade_list(rows):
    """rows: list of dict with keys date, market, code, sell_first_suspended, daytrade_volume"""
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO daytrade_list
               (date, market, code, sell_first_suspended, daytrade_volume)
               VALUES (:date,:market,:code,:sell_first_suspended,:daytrade_volume)""",
            rows,
        )


def get_daytrade_list(market: str, date: str):
    """回傳 {code: (sell_first_suspended, daytrade_volume)}；當天沒有資料回傳空 dict
    （呼叫端要把「空」視為「不知道」，而不是「全部都不能當沖」）。"""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT code, sell_first_suspended, daytrade_volume FROM daytrade_list WHERE market=? AND date=?",
            (market, date),
        )
        return {code: (bool(sfs), vol) for code, sfs, vol in cur.fetchall()}
