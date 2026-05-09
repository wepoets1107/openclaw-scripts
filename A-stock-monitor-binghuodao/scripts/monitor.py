#!/usr/bin/env python3
"""
A股期权信号监测 v2.0
数据源：akshare（SSE/SZSE PCR + QVIX）
支持历史数据回测（--date YYYYMMDD）

用法：python3 a-share-option-signal.py [--date YYYYMMDD] [--etf 300|kcb|cyb]
"""

import sys
import argparse
import akshare as ak
from datetime import datetime, timedelta

ETFS = {
    '50': {'name': '上证50ETF', 'code': '510050', 'qrix': ak.index_option_50etf_qvix, 'sse': True, 'keyword': '50ETF'},
    '300': {'name': '沪深300ETF', 'code': '510300', 'qrix': ak.index_option_300etf_qvix, 'sse': True, 'keyword': '300ETF'},
    '500': {'name': '中证500ETF', 'code': '510500', 'qrix': ak.index_option_500etf_qvix, 'sse': True, 'keyword': '500ETF'},
    'kcb': {'name': '科创50ETF', 'code': '588000', 'qrix': ak.index_option_kcb_qvix, 'sse': True, 'keyword': '科创50'},
    'cyb': {'name': '创业板ETF', 'code': '159915', 'qrix': ak.index_option_cyb_qvix, 'sse': False, 'keyword': '创业板'},
    'sz100': {'name': '深证100ETF', 'code': '159901', 'qrix': None, 'sse': False, 'keyword': '深证100'},
}

PCR_HIGH = 1.2
PCR_LOW = 0.6


def get_trade_date(date_str=None):
    if date_str:
        return date_str
    today = datetime.now()
    if today.weekday() >= 5:
        days_back = today.weekday() - 4
        today = today - timedelta(days=days_back)
    return today.strftime('%Y%m%d')


def get_qvix(etf_key, target_date=None):
    """获取QVIX + 历史分位，按指定日期匹配"""
    try:
        func = ETFS[etf_key].get('qrix')
        if func is None:
            return None
        df = func()
        if df.empty:
            return None
        closes = df['close'].dropna().tolist()
        if not closes:
            return None
        # 按目标日期匹配
        if target_date:
            try:
                target = datetime.strptime(target_date, '%Y%m%d').date()
                df['date_parsed'] = df['date'].apply(lambda x: x if hasattr(x, 'year') else pd.to_datetime(x).date())
                closest_idx = (df['date_parsed'] - target).abs().idxmin()
                latest = df.loc[closest_idx]
            except:
                latest = df.iloc[-1]
        else:
            latest = df.iloc[-1]
        current = float(latest['close'])
        qvix_min = min(closes)
        qvix_max = max(closes)
        # 30日分位
        recent_30 = closes[-30:] if len(closes) >= 30 else closes
        sorted_30 = sorted(recent_30)
        rank = sum(1 for v in sorted_30 if v <= current)
        percentile = rank / len(sorted_30) * 100
        qvix_date = str(latest['date'])
        return {
            'current': current,
            'min': qvix_min,
            'max': qvix_max,
            'avg_30': sum(recent_30) / len(recent_30),
            'percentile': percentile,
            'date': qvix_date,
        }
    except:
        return None


def get_pcr_sse(date_str, keyword):
    """上交所PCR（认沽/认购是百分比形式，需÷100）"""
    try:
        df = ak.option_daily_stats_sse(date=date_str)
        if df.empty:
            return None
        filtered = df[df['合约标的名称'].str.contains(keyword, na=False)]
        if filtered.empty:
            return None
        row = filtered.iloc[0]
        pcr = float(row['认沽/认购']) / 100  # 百分比转比率
        return {
            'pcr': pcr,
            'total_oi': int(row['未平仓合约总数']),
            'oi_call': int(row['未平仓认购合约数']),
            'oi_put': int(row['未平仓认沽合约数']),
            'total_vol': int(row['总成交量']),
            'vol_call': int(row['认购成交量']),
            'vol_put': int(row['认沽成交量']),
        }
    except:
        return None


def get_pcr_szse(date_str, keyword):
    """深交所PCR（认沽/认购持仓比是百分比形式，需÷100）"""
    try:
        df = ak.option_daily_stats_szse(date=date_str)
        if df.empty:
            return None
        filtered = df[df['合约标的名称'].str.contains(keyword, na=False)]
        if filtered.empty:
            return None
        row = filtered.iloc[0]
        pcr = float(row['认沽/认购持仓比']) / 100  # 百分比转比率
        return {
            'pcr': pcr,
            'total_oi': int(row['未平仓合约总数']),
            'oi_call': int(row['未平仓认购合约数']),
            'oi_put': int(row['未平仓认沽合约数']),
            'total_vol': int(row['成交量']),
            'vol_call': int(row['认购成交量']),
            'vol_put': int(row['认沽成交量']),
        }
    except:
        return None


def assess_qvix(qvix_data):
    """QVIX评估"""
    if not qvix_data:
        return "N/A"
    pct = qvix_data['percentile']
    if pct > 80:
        return f"偏高(分位{pct:.0f}%),期权偏贵"
    elif pct < 20:
        return f"偏低(分位{pct:.0f}%),期权偏便宜"
    else:
        return f"正常(分位{pct:.0f}%)"


def assess_pcr(pcr):
    """PCR评估"""
    if pcr is None:
        return "N/A"
    if pcr > PCR_HIGH:
        return f"{pcr:.2f} 恐慌区间,关注反转"
    elif pcr < PCR_LOW:
        return f"{pcr:.2f} 过度乐观,小心回调"
    else:
        return f"{pcr:.2f} 正常"


def suggest_strategy(qvix_data, pcr_val, pcr_data):
    """策略建议"""
    tips = []
    
    # QVIX策略
    if qvix_data:
        pct = qvix_data['percentile']
        if pct > 80:
            tips.append("QVIX偏高,卖方优势,可考虑卖出宽跨式")
        elif pct < 20:
            tips.append("QVIX偏低,买方优势,可考虑买入跨式或保护性Put")
    
    # PCR策略
    if pcr_val is not None:
        if pcr_val > PCR_HIGH:
            tips.append("PCR恐慌,可考虑卖出虚值Put或Bull Put Spread")
        elif pcr_val < PCR_LOW:
            tips.append("PCR过度乐观,可考虑保护性Put")
    
    # OI结构
    if pcr_data:
        oi_ratio = pcr_data['oi_put'] / pcr_data['oi_call'] if pcr_data['oi_call'] > 0 else 0
        if oi_ratio > 1.3:
            tips.append(f"沽购OI比{oi_ratio:.2f},Put端防守密集")
        elif oi_ratio < 0.7:
            tips.append(f"沽购OI比{oi_ratio:.2f},Call端进攻意图明显")
    
    return tips if tips else ["市场中性偏稳,可考虑Iron Condor"]


def generate_signal(date_str=None, etf_key=None):
    if date_str is None:
        date_str = get_trade_date()
    try:
        display_date = datetime.strptime(date_str, '%Y%m%d').strftime('%Y-%m-%d')
    except:
        display_date = date_str

    etfs_to_process = {etf_key: ETFS[etf_key]} if etf_key else ETFS

    lines = [f"A股期权信号播报 {display_date}", ""]

    for key, info in etfs_to_process.items():
        name = info['name']
        is_sse = info['sse']
        keyword = info['keyword']

        lines.append(f"【{name}】")

        # QVIX
        qvix = get_qvix(key, target_date=date_str)
        if qvix:
            lines.append(f"QVIX: {qvix['current']:.2f}%")
            lines.append(f"30日均值: {qvix['avg_30']:.2f}%")
            lines.append(f"30日区间: {qvix['min']:.2f}% ~ {qvix['max']:.2f}%")
            lines.append(f"分位: {qvix['percentile']:.0f}%")
            lines.append(f"评估: {assess_qvix(qvix)}")
            lines.append(f"(数据截至{qvix['date']})")
        else:
            lines.append("QVIX: 暂无数据")

        # PCR
        if is_sse:
            pcr_data = get_pcr_sse(date_str, keyword)
        else:
            pcr_data = get_pcr_szse(date_str, keyword)

        pcr_val = pcr_data['pcr'] if pcr_data else None
        pcr_text = assess_pcr(pcr_val)
        lines.append(f"PCR: {pcr_text}")

        if pcr_data:
            oi_ratio = pcr_data['oi_put'] / pcr_data['oi_call'] if pcr_data['oi_call'] > 0 else 0
            lines.append(f"OI总量: {pcr_data['total_oi']:,}")
            lines.append(f"  认购: {pcr_data['oi_call']:,}")
            lines.append(f"  认沽: {pcr_data['oi_put']:,}")
            lines.append(f"  沽购比: {oi_ratio:.2f}")
            lines.append(f"成交量: {pcr_data['total_vol']:,}")
            lines.append(f"  认购: {pcr_data['vol_call']:,}")
            lines.append(f"  认沽: {pcr_data['vol_put']:,}")

        # 策略建议
        tips = suggest_strategy(qvix, pcr_val, pcr_data)
        lines.append(f"策略: {tips[0]}")

        lines.append("")
        lines.append("━━━━━━━━━━")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', type=str, help='交易日期 YYYYMMDD')
    parser.add_argument('--etf', type=str, choices=['50', '300', '500', 'kcb', 'cyb', 'sz100'], help='指定ETF')
    args = parser.parse_args()

    date_str = args.date if args.date else get_trade_date()

    try:
        signal = generate_signal(date_str, args.etf)
        print(signal)
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
