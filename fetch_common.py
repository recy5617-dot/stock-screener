# -*- coding: utf-8 -*-
"""共用的 HTTP 請求工具：重試、延遲、統一 headers。"""

import time
import requests

from config import REQUEST_TIMEOUT_SEC, REQUEST_RETRY, REQUEST_DELAY_SEC

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.twse.com.tw/",
}

_session = requests.Session()
_session.headers.update(HEADERS)


def get_json(url: str, params: dict = None, referer: str = None):
    """GET 並回傳 JSON；失敗會重試，最後仍失敗回傳 None（呼叫端要能容忍缺資料）。"""
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer

    last_err = None
    for attempt in range(1, REQUEST_RETRY + 1):
        try:
            resp = _session.get(
                url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SEC
            )
            time.sleep(REQUEST_DELAY_SEC)
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
                continue
            return resp.json()
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(REQUEST_DELAY_SEC)
    print(f"  [警告] 請求失敗：{url} params={params} 原因={last_err}")
    return None


def to_float(s, default=0.0):
    if s is None:
        return default
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).replace(",", "").strip()
    if s in ("", "--", "---", "X", "N/A"):
        return default
    try:
        return float(s)
    except ValueError:
        return default
