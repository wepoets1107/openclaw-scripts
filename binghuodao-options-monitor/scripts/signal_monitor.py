#!/usr/bin/env python3
"""
Binghuodao Options Monitor — Signal Monitor
Detects IV anomalies, large orders, PCR extremes, basis sentiment.

Usage: python3 signal_monitor.py [btc|eth|all]  (default: all)
"""

import sys
import requests
from datetime import datetime, timezone, timedelta

DERIBIT_URL = "https://www.deribit.com/api/v2"
CURRENCIES = ['BTC', 'ETH']
PCR_HIGH = 1.2
PCR_LOW = 0.6
BASIS_HIGH = 3.0
BASIS_LOW = -2.0
LARGE_VOLUME = 1000
LARGE_OI_DELTA = 500


def deribit_call(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        r = requests.post(DERIBIT_URL, json=payload, timeout=15)
        return r.json().get('result', {})
    except Exception as e:
        return {"error": str(e)}


def get_index_price(currency):
    r = deribit_call("public/get_index_price", {"index_name": f"{currency.lower()}_usd"})
    return r.get('index_price', 0)


def get_futures(currency):
    r = deribit_call("public/get_book_summary_by_currency", {"currency": currency, "kind": "future"})
    return r if isinstance(r, list) else []


def get_options(currency):
    r = deribit_call("public/get_book_summary_by_currency", {"currency": currency, "kind": "option"})
    return r if isinstance(r, list) else []


def get_hv(currency):
    r = deribit_call("public/get_historical_volatility", {"currency": currency})
    if isinstance(r, list) and len(r):
        first = r[0]
        if isinstance(first, list) and len(first) > 1:
            sorted_r = sorted(r, key=lambda x: x[0] if isinstance(x, list) and len(x) > 0 else 0, reverse=True)
            return sorted_r[0][1]
        elif isinstance(first, dict):
            sorted_r = sorted(r, key=lambda x: x.get('timestamp', 0), reverse=True)
            return sorted_r[0].get('volatility', 0)
    return 0


def parse_expiry(name):
    try:
        parts = name.split('-')
        if len(parts) < 3:
            return None, None, None
        day = int(parts[1][:2])
        month_str = parts[1][2:5]
        year_part = parts[1][5:] if len(parts[1]) > 5 else '26'
        year = int('20' + year_part)
        month_map = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
                     'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
        month = month_map.get(month_str.upper(), 1)
        expiry_ms = datetime(year, month, day, 8, 0, tzinfo=timezone.utc).timestamp() * 1000
        strike = float(parts[2])
        is_call = '-C' in name
        return expiry_ms, strike, is_call
    except:
        return None, None, None


def calc_term_structure(options, spot):
    now = datetime.now(timezone.utc).timestamp() * 1000
    expiry_groups = {}

    for opt in options:
        name = opt.get('instrument_name', '')
        expiry_ms, strike, is_call = parse_expiry(name)
        if expiry_ms is None:
            continue
        days_to_expiry = (expiry_ms - now) / (1000 * 86400)
        if days_to_expiry < 3:
            continue
        iv = opt.get('mark_iv', 0)
        if iv <= 0:
            continue
        dist = abs(strike - spot) / spot
        if dist > 0.10:
            continue
        if expiry_ms not in expiry_groups:
            expiry_groups[expiry_ms] = []
        expiry_groups[expiry_ms].append((dist, iv, days_to_expiry, name, strike))

    term_ivs = {}
    for expiry_ms, items in expiry_groups.items():
        items.sort(key=lambda x: x[0])
        best = items[0]
        term_ivs[expiry_ms] = {'iv': best[1], 'strike': best[4], 'days': best[2], 'name': best[3]}

    sorted_expiries = sorted(term_ivs.keys())
    result = {}
    labels = ['near_week', 'near_month', 'far_month']
    display_labels = ['近周', '近月', '远月']
    for i, expiry_ms in enumerate(sorted_expiries[:3]):
        result[labels[i]] = term_ivs[expiry_ms]
        result[labels[i]]['display_label'] = display_labels[i]

    structure = "正常"
    if len(result) >= 3:
        vals = [result[labels[i]]['iv'] for i in range(3)]
        if vals[0] > vals[1] * 1.15:
            structure = "近周IV异常高,短期恐慌"
        elif vals[1] > vals[2] * 1.15:
            structure = "期限结构陡峭,远期IV偏低"
        elif vals[2] > vals[1] * 1.15:
            structure = "倒挂结构,市场看空远期"
    elif len(result) == 2:
        keys = list(result.keys())
        if result[keys[0]]['iv'] > result[keys[1]]['iv'] * 1.15:
            structure = "近月IV异常高"
        elif result[keys[1]]['iv'] > result[keys[0]]['iv'] * 1.15:
            structure = "期限结构陡峭"

    return result, structure


def calc_pcr(options):
    put_vol = sum(opt.get('volume', 0) or 0 for opt in options if '-P' in opt.get('instrument_name', ''))
    call_vol = sum(opt.get('volume', 0) or 0 for opt in options if '-C' in opt.get('instrument_name', ''))
    return put_vol / call_vol if call_vol > 0 else 0


def calc_basis(futures, spot):
    if not futures or not spot:
        return 0
    nearest = min(futures, key=lambda x: x.get('estimated_delivery_price', 999999))
    future_price = nearest.get('mark_price', 0) or nearest.get('last', 0)
    if future_price and spot:
        return ((future_price - spot) / spot) * 100
    return 0


def detect_large_orders(options, currency):
    alerts = []
    for opt in options:
        name = opt.get('instrument_name', '')
        vol = opt.get('volume', 0) or 0
        oi_change = opt.get('open_interest_change', 0) or 0
        mark_iv = opt.get('mark_iv', 0) or 0
        opt_type = "PUT" if '-P' in name else "CALL"
        if vol >= LARGE_VOLUME:
            alerts.append((vol, f"  {name} 成交{vol}张 IV={mark_iv:.1f}% ({opt_type})"))
        if oi_change >= LARGE_OI_DELTA:
            alerts.append((oi_change, f"  {name} OI增{oi_change}张 IV={mark_iv:.1f}% ({opt_type})"))
    alerts.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in alerts[:5]], len(alerts)


def generate_signal(target='all'):
    shanghai = timezone(timedelta(hours=8))
    now = datetime.now(shanghai).strftime('%Y-%m-%d %H:%M')
    currencies = CURRENCIES if target == 'all' else [target.upper()]
    
    lines = [f"【加密期权信号播报】 {now}", ""]

    for currency in currencies:
        spot = get_index_price(currency)
        futures = get_futures(currency)
        options = get_options(currency)
        hv = get_hv(currency)

        if not spot or not options:
            lines.append(f"【{currency}】数据获取失败")
            lines.append("")
            continue

        term_ivs, structure = calc_term_structure(options, spot)
        pcr = calc_pcr(options)
        basis = calc_basis(futures, spot)

        lines.append(f"【{currency}】")
        lines.append(f"现货: ${spot:,.2f} | HV: {hv:.1f}%")
        lines.append(f"期限结构: {structure}")
        lines.append("")

        # IV term detail
        if term_ivs:
            lines.append("IV期限:")
            for term in ['near_week', 'near_month', 'far_month']:
                if term in term_ivs:
                    t = term_ivs[term]
                    lines.append(f"  {t['display_label']}: {t['iv']:.1f}% (行权价{t['strike']:.0f})")
            lines.append("")

        # PCR
        pcr_signal = ""
        if pcr > PCR_HIGH:
            pcr_signal = "恐慌区间,关注反转"
        elif pcr < PCR_LOW:
            pcr_signal = "过度乐观,小心回调"
        else:
            pcr_signal = "正常"
        lines.append(f"PCR: {pcr:.2f} ({pcr_signal})")

        # Basis
        basis_signal = ""
        if basis > BASIS_HIGH:
            basis_signal = "杠杆过热"
        elif basis < BASIS_LOW:
            basis_signal = "避险情绪"
        else:
            basis_signal = "正常"
        lines.append(f"基差: {basis:+.2f}% ({basis_signal})")
        lines.append("")

        # Large orders
        top5, total = detect_large_orders(options, currency)
        if top5:
            lines.append(f"大单异动 (TOP5, 共{total}笔):")
            lines.extend(top5)
        else:
            lines.append("大单: 无异常")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("下次播报: 8小时后")
    return "\n".join(lines)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if target not in ['btc', 'eth', 'all']:
        print(f"用法: python3 {sys.argv[0]} [btc|eth|all]")
        sys.exit(1)
    try:
        signal = generate_signal(target)
        print(signal)
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
