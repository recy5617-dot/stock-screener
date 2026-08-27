# -*- coding: utf-8 -*-
"""交易日期輔助工具"""

from datetime import datetime, timedelta


def to_yyyymmdd(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def to_roc_slash(d: datetime) -> str:
    """民國年 YYY/MM/DD（部分 TPEX 舊接口使用）"""
    roc_year = d.year - 1911
    return f"{roc_year}/{d.month:02d}/{d.day:02d}"


def to_slash(d: datetime) -> str:
    return d.strftime("%Y/%m/%d")


def candidate_dates(end_date: datetime, n_days: int):
    """由 end_date 往前推，回傳最多 n_days 個「可能的交易日」(排除週六日)，
    由新到舊排列。實際是否為交易日（國定假日等）由呼叫端依 API 回應判斷。
    """
    out = []
    d = end_date
    while len(out) < n_days:
        if d.weekday() < 5:  # 0=Mon ... 4=Fri
            out.append(d)
        d = d - timedelta(days=1)
    return out
