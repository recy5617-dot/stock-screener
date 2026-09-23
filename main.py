# -*- coding: utf-8 -*-
"""
每日收盤後選股 —— 主程式
==========================
用法：
    python main.py                      # 篩選「今天」
    python main.py --date 2026-08-25    # 篩選指定日期（該日 TWSE 需已公告收盤資料，通常約 14:30後）
    python main.py --min 3              # 只列出達成數 >= 3 的股票（預設3；總共7項：7=主力觀察,5=值得研究,3=等待確認）
    python main.py --test-tpex          # 測試 TPEX 端點是否可用（見 fetch_tpex.py 說明）
    python main.py --test-big-holder    # 測試大戶持股比例(TDCC)端點是否可用（見 fetch_big_holder.py 說明）
    python main.py --backfill-only      # 只回補歷史資料，不跑選股（第一次執行建議先這樣跑，會花較久時間）
    python main.py --daytrade-only      # 只跑「隔日當沖候選名單」，不跑波段選股
    python main.py --no-daytrade        # 只跑波段選股，不跑當沖名單
    python main.py --test-daytrade      # 測試官方「可當沖標的清單」(TWTB4U) 端點是否可用

預設兩套都會跑：波段選股（7條件）＋ 隔日當沖候選名單（見 daytrade.py）。

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
import fetch_big_holder
import report
from screener import run_screen
from daytrade import run_daytrade_screen
from config import (
    MARKETS, OUTPUT_DIR, DOCS_DIR, BACKFILL_TRADING_DAYS, TIER_WATCH_MIN, TOTAL_CONDITIONS,
    ENABLE_BIG_HOLDER_CHECK, ENABLE_DAYTRADE_LIST, DT_MIN_SCORE,
)
from tradedays import to_yyyymmdd


def parse_args():
    p = argparse.ArgumentParser(description="每日收盤後選股：KD打勾＋月線上＋籌碼轉強")
    p.add_argument("--date", type=str, default=None, help="目標日期 YYYY-MM-DD，預設今天")
    p.add_argument("--min", type=int, default=TIER_WATCH_MIN, help=f"最低達成條件數（預設{TIER_WATCH_MIN}，總共{TOTAL_CONDITIONS}項）")
    p.add_argument("--backfill-days", type=int, default=BACKFILL_TRADING_DAYS, help="回補幾個交易日的歷史資料")
    p.add_argument("--backfill-only", action="store_true", help="只回補資料不跑選股")
    p.add_argument("--test-tpex", action="store_true", help="測試 TPEX 端點回應內容")
    p.add_argument("--test-big-holder", action="store_true", help="測試大戶持股比例(TDCC)端點回應內容")
    p.add_argument("--daytrade-only", action="store_true", help="只跑隔日當沖候選名單")
    p.add_argument("--no-daytrade", action="store_true", help="不跑隔日當沖候選名單")
    p.add_argument("--dt-min-score", type=float, default=DT_MIN_SCORE,
                   help=f"當沖名單最低分數（預設{DT_MIN_SCORE}）")
    p.add_argument("--test-daytrade", action="store_true", help="測試可當沖標的清單(TWTB4U)端點回應內容")
    return p.parse_args()


def main():
    args = parse_args()

    if args.test_tpex:
        fetch_tpex.test_today()
        return

    if args.test_big_holder:
        fetch_big_holder.test_today()
        return

    if args.date:
        target_dt = datetime.strptime(args.date, "%Y-%m-%d")
    else:
        target_dt = datetime.now()

    if args.test_daytrade:
        fetch_twse.test_daytrade(to_yyyymmdd(target_dt))
        return

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

    # 控制快取檔大小：GitHub 單檔上限 100MB，超過會整個 push 失敗
    deleted, size_mb = db.prune(args.backfill_days + 10)
    if deleted:
        print(f"-- 快取整理：刪除 {deleted} 筆用不到/過舊的資料，快取檔現在 {size_mb:.1f} MB --")

    if ENABLE_BIG_HOLDER_CHECK:
        print("-- 大戶持股比例(TDCC，選用功能) --")
        fetch_big_holder.fetch_and_cache_latest()

    if args.backfill_only:
        print("已完成回補（--backfill-only），結束。")
        return

    # 確認目標日期是否真的有資料（可能是假日、或當天資料還沒公告）
    has_data = any(db.list_codes_with_price_on(m, target_date_str) for m in MARKETS)
    if not has_data and not args.date:
        # 沒指定日期（例如下午2點半前手動按 Run workflow）：改用快取裡最近一個有收盤資料的交易日
        latest = db.latest_price_date(target_date_str)
        if latest:
            print(f"⚠️ {target_date_str} 還沒有收盤資料（TWSE 通常約14:30後才公告），改用最近的交易日 {latest}")
            target_date_str = latest
            has_data = True
    if not has_data:
        print(f"⚠️ {target_date_str} 目前抓不到收盤資料，可能是：")
        print("   1) 當天是假日；2) 當天資料官方還沒公告（TWSE通常約14:30後才有）；3) 網路暫時連不到官網。")
        print("   可以稍後再試，或用 --date 指定確定有交易的日期。")
        sys.exit(1)

    swing_results = run_swing(args, target_date_str) if not args.daytrade_only else None
    daytrade_results = run_daytrade(args, target_date_str) if not args.no_daytrade else None

    # ⭐ 我的關注頁：內嵌當天所有股票的收盤／漲跌，以及有沒有進兩份名單
    day_prices = [row for m in MARKETS for row in db.get_day_prices(m, target_date_str)]
    snapshot = report.build_watchlist_snapshot(target_date_str, day_prices, swing_results, daytrade_results)
    report.write_watchlist_page(snapshot, DOCS_DIR)
    print(f"已輸出我的關注頁：{os.path.join(DOCS_DIR, 'watchlist.html')}")


def run_swing(args, target_date_str):
    print(f"\n===== 開始選股（{target_date_str}，最低達成 {args.min} / {TOTAL_CONDITIONS} 項）=====")
    results, scanned_count = run_screen(target_date_str, min_checklist=args.min)
    print(f"共掃描 {scanned_count} 檔，符合條件 {len(results)} 檔")

    if not results:
        print("今天沒有股票符合門檻，可以試試調低 --min，或明天再跑。")
    else:
        header = (
            f"{'代號':<8}{'名稱':<10}{'收盤':>8}{'漲跌%':>8}  "
            f"{'①月線':<6}{'②KD':<6}{'③籌碼':<6}{'④融資':<6}{'⑤量':<6}{'⑥動能':<6}{'⑦布林':<6}"
            f"{'達成':<5}{'分級':<10}{'加權分':>7}  備註"
        )
        print("\n" + header)
        print("-" * 150)
        for r in results:
            print(
                f"{r['code']:<8}{r['name']:<10}{r['close']:>8.2f}{r['change_pct']:>7.2f}%  "
                f"{'✅' if r['cond1_ma20'] else '❌':<6}{'✅' if r['cond2_kd'] else '❌':<6}"
                f"{'✅' if r['cond3_chips'] else '❌':<6}{'✅' if r['cond4_margin_ok'] else '❌':<6}"
                f"{'✅' if r['cond5_breakout_vol'] else '❌':<6}{'✅' if r['cond6_momentum'] else '❌':<6}"
                f"{'✅' if r['cond7_bollinger'] else '❌':<6}{r['checklist_count']:<5}{r['tier']:<10}"
                f"{r['score']:>7.1f}  {r['notes']}"
            )

    out_path = os.path.join(OUTPUT_DIR, f"screen_{target_date_str}.csv")
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        fieldnames = [
            "market", "code", "name", "date", "close", "change_pct",
            "cond1_ma20", "cond2_kd", "cond3_chips", "cond4_margin_ok", "cond5_breakout_vol",
            "cond6_momentum", "cond7_bollinger",
            "checklist_count", "tier", "score", "notes",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"\n已輸出 CSV：{out_path}")

    report.write_reports(results, target_date_str, scanned_count, args.min, DOCS_DIR)
    print(f"已輸出網頁報表：{os.path.join(DOCS_DIR, 'index.html')}")
    return results


def run_daytrade(args, target_date_str):
    if ENABLE_DAYTRADE_LIST and "TWSE" in MARKETS:
        fetch_twse.fetch_and_cache_daytrade(target_date_str)

    print(f"\n===== 隔日當沖候選名單（{target_date_str}，分數 >= {args.dt_min_score}）=====")
    results, scanned_count, list_applied = run_daytrade_screen(target_date_str, min_score=args.dt_min_score)
    print(f"通過流動性濾網 {scanned_count} 檔，列出 {len(results)} 檔"
          + ("" if list_applied else "（未取得官方可當沖清單，未套用該濾網）"))

    if results:
        print(f"\n{'方向':<4}{'代號':<8}{'名稱':<10}{'收盤':>8}{'漲跌%':>8}{'ATR%':>7}{'量比':>6}{'成交億':>8}"
              f"{'分數':>7}  {'今日高':>8}{'今日低':>8}{'R1':>8}{'S1':>8}  備註")
        print("-" * 150)
        for r in results:
            print(f"{r['side']:<4}{r['code']:<8}{r['name']:<10}{r['close']:>8.2f}{r['change_pct']:>7.2f}%"
                  f"{r['atr_pct']:>7.2f}{r['vol_ratio']:>6.1f}{r['turnover_e8']:>8.1f}{r['score']:>7.1f}  "
                  f"{r['high']:>8.2f}{r['low']:>8.2f}{r['r1']:>8.2f}{r['s1']:>8.2f}  {r['notes']}")

    out_path = os.path.join(OUTPUT_DIR, f"daytrade_{target_date_str}.csv")
    fieldnames = [
        "market", "code", "name", "date", "side", "close", "change_pct",
        "volume_lots", "turnover_e8", "atr_pct", "vol_ratio", "close_pos", "daytrade_ratio",
        "condA_volatility", "condB_liquidity", "condC_volume", "condD_close", "condE_trend", "condF_chips",
        "checklist_count", "score", "high", "low", "pivot", "r1", "s1", "atr", "stop_dist", "notes",
    ]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"\n已輸出當沖 CSV：{out_path}")

    report.write_daytrade_reports(results, target_date_str, scanned_count, args.dt_min_score,
                                  list_applied, DOCS_DIR)
    print(f"已輸出當沖網頁報表：{os.path.join(DOCS_DIR, 'daytrade.html')}")
    return results


if __name__ == "__main__":
    main()
