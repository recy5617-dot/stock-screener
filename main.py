# -*- coding: utf-8 -*-
"""
每日收盤後選股 —— 主程式
==========================
用法：
    python main.py                      # 篩選「今天」
    python main.py --date 2026-08-25    # 篩選指定日期（該日 TWSE 需已公告收盤資料，通常約 14:30後）
    python main.py --min 3              # 只列出達成數 >= 3 的股票（預設3；5=主力觀察,4=值得研究,3=等待確認）
    python main.py --test-tpex          # 測試 TPEX 端點是否可用（見 fetch_tpex.py 說明）
    python main.py --backfill-only      # 只回補歷史資料，不跑選股（第一次執行建議先這樣跑，會花較久時間）

第一次執行會自動回補約 70 個交易日的歷史資料（計算 MA20 / KD / 20日高點需要），
之後每天只會抓「新的一天」，跑起來會快很多。
"""

import argparse
import csv
import os
import sys
from datetime import datetime

import db
import fetch_twse
import fetch_tpex
from screener import run_screen
from config import MARKETS, OUTPUT_DIR, BACKFILL_TRADING_DAYS
from tradedays import to_yyyymmdd


def parse_args():
    p = argparse.ArgumentParser(description="每日收盤後選股：KD打勾＋月線上＋籌碼轉強")
    p.add_argument("--date", type=str, default=None, help="目標日期 YYYY-MM-DD，預設今天")
    p.add_argument("--min", type=int, default=3, help="最低達成條件數（預設3）")
    p.add_argument("--backfill-days", type=int, default=BACKFILL_TRADING_DAYS, help="回補幾個交易日的歷史資料")
    p.add_argument("--backfill-only", action="store_true", help="只回補資料不跑選股")
    p.add_argument("--test-tpex", action="store_true", help="測試 TPEX 端點回應內容")
    return p.parse_args()


def main():
    args = parse_args()

    if args.test_tpex:
        fetch_tpex.test_today()
        return

    if args.date:
        target_dt = datetime.strptime(args.date, "%Y-%m-%d")
    else:
        target_dt = datetime.now()

    if target_dt.weekday() >= 5:
        print("⚠️ 指定的日期是週末，台股沒有交易，請改用最近的交易日。")
        sys.exit(1)

    target_date_str = to_yyyymmdd(target_dt)

    db.init_db()

    print(f"===== 回補歷史資料（目標日期 {target_date_str}，回補 {args.backfill_days} 個交易日）=====")
    for market in MARKETS:
        print(f"-- 市場：{market} --")
        if market == "TWSE":
            n = fetch_twse.fetch_and_cache_range(target_dt, args.backfill_days)
        elif market == "TPEX":
            n = fetch_tpex.fetch_and_cache_range(target_dt, args.backfill_days)
        else:
            continue
        print(f"   {market} 新抓取 {n} 個交易日")

    if args.backfill_only:
        print("已完成回補（--backfill-only），結束。")
        return

    # 確認目標日期是否真的有資料（可能是假日、或當天資料還沒公告）
    has_data = any(db.list_codes_with_price_on(m, target_date_str) for m in MARKETS)
    if not has_data:
        print(f"⚠️ {target_date_str} 目前抓不到收盤資料，可能是：")
        print("   1) 當天是假日；2) 當天資料官方還沒公告（TWSE通常約14:30後才有）；3) 網路暫時連不到官網。")
        print("   可以稍後再試，或用 --date 指定確定有交易的日期。")
        sys.exit(1)

    print(f"\n===== 開始選股（{target_date_str}，最低達成 {args.min} / 5 項）=====")
    results = run_screen(target_date_str, min_checklist=args.min)

    if not results:
        print("今天沒有股票符合門檻，可以試試調低 --min，或明天再跑。")
        return

    print(f"\n共 {len(results)} 檔符合條件：\n")
    header = f"{'代號':<8}{'名稱':<10}{'收盤':>8}{'漲跌%':>8}  {'①月線':<6}{'②KD':<6}{'③籌碼':<6}{'④融資':<6}{'⑤量':<6}{'達成':<5}{'分級':<10}{'加權分':>7}  備註"
    print(header)
    print("-" * 110)
    for r in results:
        print(
            f"{r['code']:<8}{r['name']:<10}{r['close']:>8.2f}{r['change_pct']:>7.2f}%  "
            f"{'✅' if r['cond1_ma20'] else '❌':<6}{'✅' if r['cond2_kd'] else '❌':<6}"
            f"{'✅' if r['cond3_chips'] else '❌':<6}{'✅' if r['cond4_margin_ok'] else '❌':<6}"
            f"{'✅' if r['cond5_breakout_vol'] else '❌':<6}{r['checklist_count']:<5}{r['tier']:<10}"
            f"{r['score']:>7.1f}  {r['notes']}"
        )

    out_path = os.path.join(OUTPUT_DIR, f"screen_{target_date_str}.csv")
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        fieldnames = [
            "market", "code", "name", "date", "close", "change_pct",
            "cond1_ma20", "cond2_kd", "cond3_chips", "cond4_margin_ok", "cond5_breakout_vol",
            "checklist_count", "tier", "score", "notes",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"\n已輸出：{out_path}")


if __name__ == "__main__":
    main()
