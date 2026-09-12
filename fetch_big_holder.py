# -*- coding: utf-8 -*-
"""
大戶持股比例（選用功能）
========================
資料來源：集保結算所(TDCC) 開放資料「集保股權分散表」
  https://opendata.tdcc.com.tw/getOD.ashx?id=1-5

這份資料的特性：
  - 是「純文字 CSV」，欄位：資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%
  - 持股分級是 1~17 的代碼，17 是「合計」（全部股東股數總和），
    其餘每個代碼對應一個股數區間，數字越大代表持股越多。
    代碼 12 大約對應「40萬股(約400張)以上」，是常見拿來當「大戶」門檻的慣例值
    （見 config.BIG_HOLDER_MIN_TIER），不是官方正式定義的「大戶」標準，僅供參考。
  - 這個端點固定回傳「目前最新一期」的資料，一週才更新一次（通常每週五公告），
    沒辦法用日期參數查歷史某一天，所以程式只會抓「最新一期」，
    用資料裡的「資料日期」欄位當作這筆快取的日期存下來。

開發環境對這個網域曾經測試成功抓到真實資料，但正式啟用前仍建議先手動執行
`python main.py --test-big-holder`，確認能抓到資料、比例算出來合理，再把
config.py 的 `ENABLE_BIG_HOLDER_CHECK` 打開。
"""

import csv
import io

import db
from fetch_common import get_text, to_float
from config import BIG_HOLDER_URL, BIG_HOLDER_MIN_TIER

TOTAL_TIER_CODE = "17"  # 「合計」那一列


def _parse_csv(text: str):
    """回傳 (data_date, {code: big_holder_pct})。抓不到就回傳 (None, {})。"""
    if not text:
        return None, {}
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return None, {}

    header = rows[0]
    idx = {name.strip(): i for i, name in enumerate(header)}
    required = ["資料日期", "證券代號", "持股分級", "股數"]
    if not all(k in idx for k in required):
        return None, {}

    big_shares = {}
    total_shares = {}
    data_date = None
    for row in rows[1:]:
        try:
            date_val = row[idx["資料日期"]].strip()
            code = row[idx["證券代號"]].strip()
            tier = row[idx["持股分級"]].strip()
            shares = to_float(row[idx["股數"]])
        except (IndexError, AttributeError):
            continue
        if not date_val or not code:
            continue
        data_date = data_date or date_val

        if tier == TOTAL_TIER_CODE:
            total_shares[code] = shares
        else:
            try:
                tier_num = int(tier)
            except ValueError:
                continue
            if tier_num >= BIG_HOLDER_MIN_TIER:
                big_shares[code] = big_shares.get(code, 0.0) + shares

    pct_map = {}
    for code, total in total_shares.items():
        if total > 0:
            pct_map[code] = big_shares.get(code, 0.0) / total * 100.0
    return data_date, pct_map


def fetch_and_cache_latest():
    """抓「目前最新一期」大戶持股比例，若這個資料日期已經存過就跳過，回傳 (data_date, 檔數)。"""
    text = get_text(BIG_HOLDER_URL)
    data_date, pct_map = _parse_csv(text)
    if not data_date or not pct_map:
        print("  [大戶持股] 沒有抓到資料（可能是端點格式變了，或暫時連不上）")
        return None, 0

    rows = [{"date": data_date, "code": code, "big_holder_pct": pct} for code, pct in pct_map.items()]
    db.save_big_holder(rows)
    print(f"  [大戶持股] 資料日期 {data_date}，共 {len(rows)} 檔")
    return data_date, len(rows)


def test_today():
    """給 `python main.py --test-big-holder` 用：抓一次資料，印出幾檔範例，方便人工檢查格式對不對。"""
    text = get_text(BIG_HOLDER_URL)
    if not text:
        print("抓不到任何內容，可能是網路被擋，或端點網址失效。")
        return
    print("=== 原始內容前 5 行 ===")
    for line in text.splitlines()[:5]:
        print(line)

    data_date, pct_map = _parse_csv(text)
    print(f"\n解析出的資料日期：{data_date}")
    print(f"解析出幾檔股票的大戶持股比例：{len(pct_map)}")
    print(f"（大戶門檻：持股分級代碼 >= {BIG_HOLDER_MIN_TIER}）")
    print("\n=== 範例（前10檔）===")
    for code, pct in list(pct_map.items())[:10]:
        print(f"  {code}: {pct:.2f}%")
    if pct_map:
        print("\n如果上面比例數字看起來合理（通常大股東比例會落在幾%到幾十%之間），"
              "可以放心把 config.py 的 ENABLE_BIG_HOLDER_CHECK 改成 True。")
