#!/usr/bin/env python3
import json
import math
import os
import statistics
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone, timedelta

BASE_URL = "https://market.ft.tech"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "latest.json")


def get_json(path, params=None):
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-Client-Name": "ft-claw"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def pct(value):
    return f"{value * 100:+.2f}%"


def amount_yi(value):
    return f"{value / 100000000:.2f} 亿"


def strength(change_rate):
    return max(8, min(96, round(50 + change_rate * 1800)))


def index_detail(symbol):
    return get_json(
        f"/app/api/v2/indices/{symbol}",
        {"masks": "name,symkey,latest,change_rate,turnover"}
    )


def stock_list(order_by, page_size):
    return get_json(
        "/app/api/v2/stocks",
        {
            "order_by": order_by,
            "filter": "change_rate != null",
            "masks": "name,symkey,industry_sector,latest,change_rate,turnover,turnover_rate,trading_status",
            "page_no": 1,
            "page_size": page_size
        }
    )["stocks"]


def index_list():
    return get_json(
        "/app/api/v2/indices",
        {
            "order_by": "change_rate desc",
            "masks": "name,symkey,latest,change_rate,turnover",
            "page_no": 1,
            "page_size": 20
        }
    )["indices"]


def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    main_indices = [
        index_detail("000001.XSHG"),
        index_detail("399001.XSHE"),
        index_detail("399006.XSHE"),
        index_detail("899050.BJSE")
    ]
    top_stocks = stock_list("change_rate desc", 40)
    weak_stocks = stock_list("change_rate asc", 30)
    top_indices = index_list()

    avg_change = statistics.mean(item["change_rate"] for item in main_indices)
    limit_up = sum(1 for item in top_stocks if item.get("trading_status") == "LIMIT_UP")
    limit_down = sum(1 for item in weak_stocks if item.get("trading_status") == "LIMIT_DOWN")
    heat = max(15, min(88, round(50 + avg_change * 1200 + limit_up * 0.8 - limit_down * 1.4)))
    status = "偏强" if heat >= 62 else "偏弱" if heat <= 45 else "中性"

    sector_counter = Counter()
    for item in top_stocks[:30]:
        sector = item.get("industry_sector") or {}
        sector_counter[sector.get("name") or "其他"] += 1

    sectors = []
    for name, _ in sector_counter.most_common(5):
        members = [s for s in top_stocks if (s.get("industry_sector") or {}).get("name") == name]
        avg = statistics.mean(s["change_rate"] for s in members)
        sectors.append([name, pct(avg), strength(avg), False])

    index_rows = [
        [item["name"], pct(item["change_rate"]), str(round(item["latest"], 4)), strength(item["change_rate"])]
        for item in main_indices
    ]

    stock_rows = []
    for item in top_stocks[:7]:
        sector = (item.get("industry_sector") or {}).get("name") or "其他"
        stock_rows.append([
            item["name"],
            item["symkey"].split(".")[0],
            sector,
            pct(item["change_rate"]),
            amount_yi(item["turnover"]),
            str(strength(item["change_rate"])),
            "强势，观察承接",
            "core" if item.get("trading_status") == "LIMIT_UP" else "volume"
        ])
    for item in weak_stocks[:3]:
        sector = (item.get("industry_sector") or {}).get("name") or "其他"
        stock_rows.append([
            item["name"],
            item["symkey"].split(".")[0],
            sector,
            pct(item["change_rate"]),
            amount_yi(item["turnover"]),
            str(strength(item["change_rate"])),
            "风险释放，先等止跌",
            "risk"
        ])

    active_by_turnover = sorted(top_stocks, key=lambda item: item.get("turnover") or 0, reverse=True)[:3]
    volume_signals = [
        [item["name"], f"成交额约{amount_yi(item['turnover'])}，短线活跃度靠前。", "hot", amount_yi(item["turnover"])]
        for item in active_by_turnover
    ]
    risk_signals = [
        ["弱势股压力", "跌幅榜前排仍有高波动品种，早盘不急于反核。", "warn", "风险"],
        ["指数环境", "主要指数若同步走弱，强势股追高需要更看重承接。", "warn", status],
        ["数据口径", "集合竞价专用字段不可直接取得，网页使用开盘后行情替代。", "cool", "替代"]
    ]

    total_turnover = sum(item.get("turnover") or 0 for item in main_indices)
    headline = "市场偏强，强势股可看承接" if heat >= 62 else "指数偏弱，先看结构机会" if heat <= 45 else "市场中性，等待方向确认"

    data = {
        "generated_at": now.isoformat(timespec="seconds"),
        "source_note": "集合竞价专用字段暂不可直接取得，使用开盘后/当前行情替代。",
        "market": {
            "heat": heat,
            "headline": headline,
            "summary": f"主要指数平均涨跌幅 {pct(avg_change)}；强势方向集中在 {', '.join(name for name, *_ in sectors[:3])}。当前口径为开盘后行情替代集合竞价快照。",
            "breadth": status,
            "amount": amount_yi(total_turnover),
            "limitUp": limit_up,
            "limitDown": limit_down,
            "indices": index_rows,
            "sectors": sectors,
            "signals": [
                ["市场状态", f"竞价温度 {heat}/100，状态判断为{status}。", "hot" if heat >= 62 else "warn" if heat <= 45 else "cool"],
                ["强势方向", f"{', '.join(name for name, *_ in sectors[:3])} 相对活跃。", "hot"],
                ["口径提示", "集合竞价专用字段不可直接取得，使用开盘后行情替代。", "cool"]
            ]
        },
        "stocks": stock_rows,
        "volumeSignals": volume_signals,
        "riskSignals": risk_signals
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
