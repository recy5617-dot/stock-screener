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


def list_codes_with_price_on(market: str, date: str):
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT code, name FROM prices WHERE market=? AND date=?", (market, date)
        )
        return cur.fetchall()
