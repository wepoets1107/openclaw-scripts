#!/usr/bin/env python3
"""
Binghuodao Options Monitor — DVOL Snapshot
Real-time DVOL (Deribit Volatility Index) data for BTC and ETH.

Uses Deribit public API: public/get_volatility_index_data
Format: [timestamp, open, high, low, close]

Usage: python3 dvol_snapshot.py [btc|eth|all]  (default: all)
"""

import sys
import time
import requests
from datetime import datetime, timezone, timedelta

DERIBIT_URL = "https://www.deribit.com/api/v2"
CURRENCIES = ['BTC', 'ETH']


def deribit_call(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        r = requests.post(DERIBIT_URL, json=payload, timeout=15)
        return r.json().get('result', {})
    except Exception as e:
        return {"error": str(e)}


def get_dvol_data(currency, days=30):
    """Get DVOL historical data from Deribit"""
    end_ts = int(time.time() * 1000)
    start_ts = int((time.time() - days * 86400) * 1000)
    
    r = deribit_call("public/get_volatility_index_data", {
        "currency": currency,
        "start_timestamp": start_ts,
        "end_timestamp": end_ts,
        "resolution": "1D"
    })
    
    if isinstance(r, dict) and 'data' in r:
        return r['data']
    return []


def get_index_price(currency):
    r = deribit_call("public/get_index_price", {"index_name": f"{currency.lower()}_usd"})
    return r.get('index_price', 0)


def generate_dvol_snapshot(target='all'):
    shanghai = timezone(timedelta(hours=8))
    now = datetime.now(shanghai).strftime('%Y-%m-%d %H:%M')
    currencies = CURRENCIES if target == 'all' else [target.upper()]
    
    lines = [f"【DVOL波动率快照】 {now}", ""]

    for currency in currencies:
        spot = get_index_price(currency)
        dvol_history = get_dvol_data(currency, days=30)

        lines.append(f"【{currency}】")
        lines.append(f"现货: ${spot:,.2f}")

        if not dvol_history:
            lines.append("DVOL: 数据获取失败")
            lines.append("")
            lines.append("---")
            lines.append("")
            continue

        # Latest DVOL value (last close)
        latest = dvol_history[-1]
        current_dvol = latest[4]  # close
        dvol_high_1d = latest[2]
        dvol_low_1d = latest[3]

        lines.append(f"DVOL: {current_dvol:.2f}")
        lines.append(f"今日区间: {dvol_low_1d:.2f} - {dvol_high_1d:.2f}")

        # Historical stats
        closes = [d[4] for d in dvol_history]
        if len(closes) >= 7:
            last_7d = closes[-7:]
            lines.append(f"7日: 均值{sum(last_7d)/len(last_7d):.2f} 高{max(last_7d):.2f} 低{min(last_7d):.2f}")
        if len(closes) >= 30:
            last_30d = closes[-30:]
            avg_30 = sum(last_30d) / len(last_30d)
            lines.append(f"30日: 均值{avg_30:.2f} 高{max(last_30d):.2f} 低{min(last_30d):.2f}")

            # Percentile assessment
            sorted_closes = sorted(closes)
            rank = 0
            for i, v in enumerate(sorted_closes):
                if v >= current_dvol:
                    rank = i
                    break
            percentile = rank / len(sorted_closes) * 100
            
            if percentile > 80:
                lines.append(f"分位: {percentile:.0f}% (偏高,期权偏贵)")
            elif percentile < 20:
                lines.append(f"分位: {percentile:.0f}% (偏低,期权偏便宜)")
            else:
                lines.append(f"分位: {percentile:.0f}% (正常区间)")
            
            # 24h change
            if len(closes) >= 2:
                prev_close = closes[-2]
                change = current_dvol - prev_close
                change_pct = (change / prev_close * 100) if prev_close > 0 else 0
                lines.append(f"24h变化: {change:+.2f} ({change_pct:+.1f}%)")

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if target not in ['btc', 'eth', 'all']:
        print(f"用法: python3 {sys.argv[0]} [btc|eth|all]")
        sys.exit(1)
    try:
        snapshot = generate_dvol_snapshot(target)
        print(snapshot)
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
