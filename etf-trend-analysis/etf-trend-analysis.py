#!/usr/bin/env python3
"""
创业板&科创板ETF走势分析 - 数据采集
数据源: 灵犀API(行情) + 腾讯K线(均线/HV) + akshare(QVIX)
"""
import json, os, subprocess, sys, time
import numpy as np
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# 灵犀路径
LINGXI_SKILL_DIR = os.path.expanduser("~/.openclaw/workspace/skills/lingxi-realtimemarketdata-skill")
LINGXI_ENTRY = os.path.join(LINGXI_SKILL_DIR, "skill-entry.js")

ETFS = {
    '588000': {'name': '科创50ETF', 'lcode': 'SH588000', 'market': 'sh'},
    '159915': {'name': '创业板ETF', 'lcode': 'SZ159915', 'market': 'sz'},
}

def get_realtime_lingxi():
    """灵犀API获取实时行情"""
    codes = ','.join(v['lcode'] for v in ETFS.values())
    result = {}
    try:
        r = subprocess.run(
            ['node', LINGXI_ENTRY, 'mcpClient', 'call', 'market', 'marketdata-tool',
             f'reduced_codes={codes}'],
            capture_output=True, text=True, timeout=15, cwd=LINGXI_SKILL_DIR)
        current_code = None
        for line in r.stdout.split('\n'):
            line = line.strip()
            if not line: continue
            for code, info in ETFS.items():
                if info['lcode'] in line:
                    current_code = code
                    result[code] = {'name': info['name']}
                    break
            if current_code and current_code in result:
                if '最新价' in line:
                    try: result[current_code]['price'] = float(line.split('：')[1].replace('元','').strip())
                    except: pass
                elif '涨跌幅' in line:
                    try: result[current_code]['change_pct'] = float(line.split('：')[1].replace('%','').replace('+','').strip())
                    except: pass
                elif '成交额' in line:
                    try: result[current_code]['turnover'] = float(line.split('：')[1].replace('亿','').strip())
                    except: pass
                elif '换手率' in line:
                    try: result[current_code]['turnover_rate'] = float(line.split('：')[1].replace('%','').strip())
                    except: pass
                elif '当日资金净流入' in line:
                    try: result[current_code]['net_inflow'] = float(line.split('：')[1].replace('万元','').replace(',','').strip())
                    except: pass
    except Exception as e:
        print(f"灵犀行情失败: {e}", file=sys.stderr)
    return result

def get_klines(code, days=80):
    """腾讯K线"""
    market = ETFS[code]['market']
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {'param': f'{market}{code},day,,,{days+30},'}
    try:
        r = requests.get(url, params=params, timeout=10)
        d = r.json()
        for key in d.get('data', {}):
            sub = d['data'][key]
            for k in ['qfqday', 'day']:
                if k in sub and sub[k]:
                    return sub[k]
    except: pass
    return []

def get_qvix():
    """akshare获取QVIX"""
    result = {}
    try:
        import akshare as ak
    except: return result
    funcs = {'科创50': ak.index_option_kcb_qvix, '创业板': ak.index_option_cyb_qvix}
    for name, func in funcs.items():
        try:
            df = func()
            if len(df) > 0:
                result[name] = {'close': float(df.iloc[-1]['close']), 'date': str(df.iloc[-1]['date'])}
        except: pass
    return result

def analyze_etf(code, klines, realtime, qvix_data):
    """单ETF分析"""
    info = ETFS[code]
    closes = np.array([float(k[2]) for k in klines])
    highs = np.array([float(k[3]) for k in klines])
    lows = np.array([float(k[4]) for k in klines])
    vols = np.array([float(k[5]) for k in klines])
    dates = [k[0] for k in klines]

    current = closes[-1]
    ma5 = closes[-5:].mean()
    ma20 = closes[-20:].mean() if len(closes) >= 20 else 0
    ma60 = closes[-60:].mean() if len(closes) >= 60 else 0
    week_chg = (current / closes[-5] - 1) * 100 if len(closes) >= 5 else 0
    hi30 = highs[-30:].max()
    lo30 = lows[-30:].min()
    hi5 = highs[-5:].max()
    lo5 = lows[-5:].min()

    log_ret = np.log(closes[1:] / closes[:-1])
    hv30 = float(np.std(log_ret[-30:]) * np.sqrt(252)) * 100
    hv10 = float(np.std(log_ret[-10:]) * np.sqrt(252)) * 100

    vol5 = vols[-5:].mean()
    vol20 = vols[-20:].mean() if len(vols) >= 20 else vol5
    vol_ratio = vol5 / vol20 if vol20 > 0 else 1

    trend = '多头排列' if (ma5 > ma20 > ma60) else ('空头排列' if (ma5 < ma20 < ma60) else '交叉')

    qvix_key = '科创50' if '科创' in info['name'] else '创业板'
    qvix = qvix_data.get(qvix_key, {})
    qvix_val = qvix.get('close', 0)

    # 量价背离判断
    price_dir = '上行' if current > ma20 else '下行'
    if vol_ratio < 0.8 and price_dir == '上行':
        vol_signal = '缩量上行(背离)'
    elif vol_ratio > 1.2 and price_dir == '上行':
        vol_signal = '放量上行'
    elif vol_ratio < 0.8 and price_dir == '下行':
        vol_signal = '缩量下行'
    else:
        vol_signal = f'正常{price_dir}'

    # IV溢价
    iv_premium = ''
    if qvix_val > 0:
        if hv30 > qvix_val:
            iv_premium = f'HV30({hv30:.1f}%)>QVIX({qvix_val:.1f}%) 实际波动超隐含预期，期权定价偏低，卖方需谨慎'
        else:
            iv_premium = f'QVIX({qvix_val:.1f}%)>HV30({hv30:.1f}%) 隐含溢价，卖方优势'

    # 关键价位
    # 找近5日低点做支撑1
    support1 = lo5
    support2 = ma20
    pressure1 = hi5
    pressure2 = hi30

    # 近5日走势
    recent = []
    for i in range(-5, 0):
        chg = (closes[i] / closes[i-1] - 1) * 100
        recent.append(f"{dates[i]}: {closes[i]:.3f} ({chg:+.2f}%)")

    # 策略方向
    strategy = ''
    if qvix_val > 0:
        if trend == '多头排列':
            if hv30 > qvix_val:
                strategy = '趋势多头+IV偏低 → 卖Put胜率高于卖Call；激进可买ATM Call抓逼空'
            else:
                strategy = '趋势多头+IV溢价 → 卖Put收权利金，方向+时间双收割'
        else:
            if hv30 > qvix_val:
                strategy = '趋势不明+IV偏低 → 做多波动率(买Straddle)或观望'
            else:
                strategy = '趋势不明+IV溢价 → 卖宽跨Strangle收时间价值'

    rt = realtime.get(code, {})
    net_inflow = rt.get('net_inflow', 0)
    net_inflow_yi = net_inflow / 10000 if net_inflow else 0

    return {
        'name': info['name'], 'code': code,
        'price': rt.get('price', current), 'change_pct': rt.get('change_pct', 0),
        'week_chg': week_chg,
        'ma5': ma5, 'ma20': ma20, 'ma60': ma60, 'trend': trend,
        'hi30': hi30, 'lo30': lo30, 'hi5': hi5, 'lo5': lo5,
        'hv10': hv10, 'hv30': hv30, 'qvix': qvix_val, 'qvix_date': qvix.get('date',''),
        'iv_premium': iv_premium,
        'turnover': rt.get('turnover', 0), 'turnover_rate': rt.get('turnover_rate', 0),
        'net_inflow_yi': net_inflow_yi,
        'vol_ratio': vol_ratio, 'vol_signal': vol_signal,
        'support1': support1, 'support2': support2,
        'pressure1': pressure1, 'pressure2': pressure2,
        'recent': recent, 'strategy': strategy,
    }

def main():
    t0 = time.time()
    print(f"=== 创业板&科创板走势分析 数据采集 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # 并行
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_rt = ex.submit(get_realtime_lingxi)
        f_k1 = ex.submit(get_klines, '588000')
        f_k2 = ex.submit(get_klines, '159915')
        f_qv = ex.submit(get_qvix)

        realtime = f_rt.result(timeout=20)
        klines_588 = f_k1.result(timeout=15)
        klines_159 = f_k2.result(timeout=15)
        qvix = f_qv.result(timeout=60)

    a1 = analyze_etf('588000', klines_588, realtime, qvix)
    a2 = analyze_etf('159915', klines_159, realtime, qvix)

    # 输出
    now_str = datetime.now().strftime('%Y年%-m月%-d日（%a）')
    now_str = now_str.replace('Mon','周一').replace('Tue','周二').replace('Wed','周三').replace('Thu','周四').replace('Fri','周五')

    print(f"\n冰火岛 · 创业板&科创板ETF走势分析")
    print(f"{now_str}\n")

    for a in [a2, a1]:  # 创业板在前
        print(f"━━ {a['name']} ({a['code']}) ━━")
        print(f"\n【价格与趋势】")
        print(f"最新 {a['price']:.3f} ({a['change_pct']:+.2f}%) | 周涨跌 {a['week_chg']:+.1f}%")
        print(f"MA5={a['ma5']:.3f} MA20={a['ma20']:.3f} MA60={a['ma60']:.3f} — {a['trend']}")
        print(f"30日高 {a['hi30']:.3f} 低 {a['lo30']:.3f} | 距高{((a['price']/a['hi30'])-1)*100:.1f}% 距低{((a['price']/a['lo30'])-1)*100:+.1f}%")

        print(f"\n【波动率画像】")
        print(f"HV10={a['hv10']:.1f}%  HV30={a['hv30']:.1f}%")
        if a['qvix'] > 0:
            print(f"QVIX={a['qvix']:.2f}（{a['qvix_date']}）")
            print(f"{a['iv_premium']}")
        else:
            print(f"QVIX: 无数据")

        print(f"\n【资金与情绪】")
        print(f"成交额 {a['turnover']:.1f}亿 | 换手率 {a['turnover_rate']:.1f}% | 净流入 {a['net_inflow_yi']:+.1f}亿")
        print(f"量比5/20={a['vol_ratio']:.2f} {a['vol_signal']}")

        print(f"\n【关键价位】")
        print(f"支撑1: {a['support1']:.3f}（近5日低点）支撑2: {a['support2']:.3f}（MA20）")
        print(f"压力1: {a['pressure1']:.3f}（近5日高点）压力2: {a['pressure2']:.3f}（30日高）")

        print(f"\n【策略方向】")
        print(f"{a['strategy']}")
        print()

    # 对比
    print(f"━━ 对比 ━━")
    if a1['week_chg'] > a2['week_chg']:
        faster, slower = a1, a2
    else:
        faster, slower = a2, a1
    print(f"{faster['name']}弹性领先：周涨{faster['week_chg']:+.1f}% vs {slower['name']}{slower['week_chg']:+.1f}%")
    hv_diff = abs(a1['hv30'] - a2['hv30'])
    if a1['hv30'] > a2['hv30']:
        print(f"{a1['name']}波动率更高：HV30={a1['hv30']:.1f}% vs {a2['name']}={a2['hv30']:.1f}%（差{hv_diff:.1f}个百分点）")
    if a1['qvix'] > 0 and a2['qvix'] > 0:
        iv_gap1 = a1['hv30'] - a1['qvix']
        iv_gap2 = a2['hv30'] - a2['qvix']
        if abs(iv_gap1) > abs(iv_gap2):
            print(f"{a1['name']}的HV-QVIX剪刀差更大（{iv_gap1:+.1f}pp），期权定价失配更严重")

    print(f"\n=== 完成 耗时{time.time()-t0:.1f}s ===")

if __name__ == '__main__':
    main()
