#!/usr/bin/env python3
"""
Binghuodao Options Monitor — Daily Report
Crypto options daily report via Deribit public API.

Usage: python3 daily_report.py [btc|eth|all]  (default: all)
"""

import sys
import time
import requests
from datetime import datetime, timezone, timedelta

DERIBIT_URL = "https://www.deribit.com/api/v2"
CURRENCIES = ['BTC', 'ETH']

PCR_HIGH = 1.2
PCR_LOW = 0.6
BASIS_HIGH = 3.0
BASIS_LOW = -2.0


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


def get_dvol(currency):
    """Get DVOL index value from Deribit via get_volatility_index_data"""
    end_ts = int(time.time() * 1000)
    start_ts = int((time.time() - 86400) * 1000)
    r = deribit_call("public/get_volatility_index_data", {
        "currency": currency,
        "start_timestamp": start_ts,
        "end_timestamp": end_ts,
        "resolution": "1D"
    })
    if isinstance(r, dict) and 'data' in r and r['data']:
        return r['data'][-1][4]  # latest close
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

    # Term structure judgment
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


def get_oi_volume_ranking(options, spot, top_n=3):
    """Get OI Top N and Volume Top N"""
    valid = [opt for opt in options if opt.get('mark_iv', 0) and opt.get('instrument_name', '')]
    
    by_oi = sorted(valid, key=lambda x: x.get('open_interest', 0) or 0, reverse=True)[:top_n]
    by_vol = sorted(valid, key=lambda x: x.get('volume', 0) or 0, reverse=True)[:top_n]
    
    return by_oi, by_vol


def generate_report(target='all'):
    shanghai = timezone(timedelta(hours=8))
    now = datetime.now(shanghai).strftime('%Y-%m-%d')
    
    currencies = CURRENCIES if target == 'all' else [target.upper()]
    lines = [f"【加密期权精华日报】 {now}", ""]

    for currency in currencies:
        spot = get_index_price(currency)
        futures = get_futures(currency)
        options = get_options(currency)
        hv = get_hv(currency)
        dvol = get_dvol(currency)

        if not spot or not options:
            lines.append(f"【{currency}】数据获取失败")
            lines.append("")
            continue

        term_ivs, structure = calc_term_structure(options, spot)
        pcr = calc_pcr(options)
        basis = calc_basis(futures, spot)
        oi_top, vol_top = get_oi_volume_ranking(options, spot)
        
        # HV vs IV
        iv_assessment = ""
        if term_ivs:
            avg_iv = sum(v['iv'] for v in term_ivs.values()) / len(term_ivs)
            if hv > 0:
                iv_ratio = avg_iv / hv
                if iv_ratio > 1.3:
                    iv_assessment = f"期权偏贵 (IV/HV={iv_ratio:.2f})"
                elif iv_ratio < 0.8:
                    iv_assessment = f"期权偏便宜 (IV/HV={iv_ratio:.2f})"
                else:
                    iv_assessment = f"期权定价合理 (IV/HV={iv_ratio:.2f})"

        lines.append(f"【{currency}】")
        lines.append(f"现货: ${spot:,.2f} | HV: {hv:.1f}% | DVOL: {dvol:.1f}")
        lines.append(f"期限结构: {structure}")
        lines.append(f"IV估值: {iv_assessment}")
        lines.append("")

        # IV term structure
        if term_ivs:
            lines.append("IV期限结构:")
            for term in ['near_week', 'near_month', 'far_month']:
                if term in term_ivs:
                    t = term_ivs[term]
                    lines.append(f"  {t['display_label']}: IV={t['iv']:.1f}% 行权价={t['strike']:.0f} 剩余{t['days']:.0f}天")
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

        # OI Top 3
        if oi_top:
            lines.append("OI排行 TOP3:")
            for i, opt in enumerate(oi_top, 1):
                name = opt.get('instrument_name', '')
                oi = opt.get('open_interest', 0) or 0
                mark_iv = opt.get('mark_iv', 0) or 0
                lines.append(f"  {i}. {name} OI={oi} IV={mark_iv:.1f}%")
            lines.append("")

        # Volume Top 3
        if vol_top:
            lines.append("成交量排行 TOP3:")
            for i, opt in enumerate(vol_top, 1):
                name = opt.get('instrument_name', '')
                vol = opt.get('volume', 0) or 0
                mark_iv = opt.get('mark_iv', 0) or 0
                lines.append(f"  {i}. {name} Vol={vol} IV={mark_iv:.1f}%")
            lines.append("")

        # Strategy suggestion
        lines.append("策略建议:")
        if pcr > PCR_HIGH:
            lines.append("  PCR恐慌区间,可考虑卖出虚值Put或Bull Put Spread")
        elif pcr < PCR_LOW:
            lines.append("  PCR过度乐观,可考虑保护性Put或Bear Put Spread")
        elif structure == "倒挂结构,市场看空远期":
            lines.append("  期限结构倒挂,可考虑日历价差(Calendar Spread)卖近买远")
        elif structure == "近周IV异常高,短期恐慌":
            lines.append("  近周IV飙升,可考虑卖出短期宽跨式(Short Strangle)")
        else:
            if basis > BASIS_HIGH:
                lines.append("  基差过热,可考虑卖出虚值Call+买入远月Put对冲")
            else:
                lines.append("  市场中性偏稳,可考虑Iron Condor收取权利金")
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
        report = generate_report(target)
        print(report)
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
