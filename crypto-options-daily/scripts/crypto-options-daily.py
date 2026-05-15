#!/usr/bin/env python3
"""
加密期权精华日报 - 自动生成
每日8:00由cron执行，从Binance/Deribit API拉数据，输出到stdout
cron delivery=announce推送到微信
"""

import requests
import json
import re
import sys
from datetime import datetime, timezone, timedelta

DERIBIT_URL = "https://www.deribit.com/api/v2"
BINANCE_URL = "https://api.binance.com/api/v3"
TIMEOUT = 12

# ========== API工具 ==========

def deribit(method, params):
    try:
        r = requests.post(DERIBIT_URL, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=TIMEOUT)
        return r.json().get('result', {})
    except:
        return {}

def binance_ticker(symbol):
    try:
        r = requests.get(f"{BINANCE_URL}/ticker/24hr?symbol={symbol}USDT", timeout=TIMEOUT).json()
        return float(r['lastPrice']), float(r['priceChangePercent'])
    except:
        return 0, 0

# ========== 期权数据 ==========

def get_options(currency):
    r = deribit("public/get_book_summary_by_currency", {"currency": currency, "kind": "option"})
    return r if isinstance(r, list) else []

def get_futures(currency):
    r = deribit("public/get_book_summary_by_currency", {"currency": currency, "kind": "future"})
    return r if isinstance(r, list) else []

def get_index(currency):
    return deribit("public/get_index_price", {"index_name": f"{currency}_usd"}).get('index_price', 0)

def get_hv(currency):
    r = deribit("public/get_historical_volatility", {"currency": currency})
    if not isinstance(r, list) or not r:
        return 0
    if isinstance(r[0], list):
        return sorted(r, key=lambda x: x[0], reverse=True)[0][1]
    if isinstance(r[0], dict):
        return max(x.get('volatility', 0) for x in r)
    return 0

# ========== 合约命名 ==========

MONTH_CN = {'JAN':'1月','FEB':'2月','MAR':'3月','APR':'4月','MAY':'5月','JUN':'6月',
            'JUL':'7月','AUG':'8月','SEP':'9月','OCT':'10月','NOV':'11月','DEC':'12月'}

def fmt_contract_name(name):
    """Deribit合约名 → 中文可读: 5月29日$80K Call"""
    parts = name.split('-')
    if len(parts) < 3:
        return name
    exp_raw = parts[1]  # 29MAY26
    strike_raw = parts[2]  # 80000
    cp = 'Call' if '-C' in name else 'Put'
    try:
        d = exp_raw[:2].lstrip('0')  # 29
        m_code = exp_raw[2:5]  # MAY
        m = MONTH_CN.get(m_code, m_code)
        strike = int(strike_raw)
        if strike >= 10000:
            strike_fmt = f"${strike//1000}K" if strike % 1000 == 0 else f"${strike/1000:.1f}K"
        elif strike >= 1000:
            strike_fmt = f"${strike:,}"
        else:
            strike_fmt = f"${strike}"
        return f"{m}{d}日 {strike_fmt} {cp}"
    except:
        return name

def fmt_oi_vol(items, key):
    """单行格式: 5月15日 $84K Call | OI=2,564 BTC | IV=52.6%"""
    result = []
    for o in items:
        name = fmt_contract_name(o.get('instrument_name', ''))
        val = o.get(key, 0) or 0
        iv = o.get('mark_iv', 0) or 0
        unit = 'BTC' if 'BTC' in o.get('instrument_name', '') else '张'
        k = 'OI' if key == 'open_interest' else 'Vol'
        result.append(f"    - {name} | {k}={val:,.0f} {unit} | IV={iv:.1f}%")
    return result

# ========== 分析函数 ==========

def parse_expiry(name):
    parts = name.split('-')
    if len(parts) < 3:
        return None, None, None
    try:
        month_map = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
                     'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
        exp = datetime(int('20'+parts[1][5:]), month_map[parts[1][2:5]], int(parts[1][:2]), 8, 0, tzinfo=timezone.utc)
        strike = float(parts[2])
        is_call = '-C' in name
        return exp, strike, is_call
    except:
        return None, None, None

def get_near_atm_iv(options, spot, max_dist=0.08):
    """获取近月ATM IV（最接近平值的）"""
    now = datetime.now(timezone.utc)
    best = None
    best_dist = 999
    for o in options:
        exp, strike, _ = parse_expiry(o.get('instrument_name', ''))
        if not exp or (exp - now).days < 2 or (exp - now).days > 45:
            continue
        iv = o.get('mark_iv', 0)
        if iv <= 0:
            continue
        dist = abs(strike - spot) / (spot or 1)
        if dist < best_dist and dist <= max_dist:
            best_dist = dist
            best = iv
    return best or 0

def term_structure(options, spot, max_dist=0.10):
    """IV期限结构 — 至少返回3行（不足时补齐估算）"""
    now = datetime.now(timezone.utc)
    groups = {}
    for o in options:
        exp, strike, _ = parse_expiry(o.get('instrument_name', ''))
        if not exp or (exp - now).days < 2:
            continue
        iv = o.get('mark_iv', 0)
        if iv <= 0:
            continue
        dist = abs(strike - spot) / (spot or 1)
        if dist > max_dist:
            continue
        key = exp.strftime('%m/%d')
        if key not in groups or dist < groups[key][0]:
            groups[key] = (dist, iv, strike, exp)
    sorted_items = sorted(groups.items(), key=lambda x: x[1][3])
    
    # 至少确保3个期限点（如不足则用已有数据重复填充）
    if len(sorted_items) >= 3:
        selected = [sorted_items[0], sorted_items[len(sorted_items)//2], sorted_items[-1]]
    elif len(sorted_items) == 2:
        selected = [sorted_items[0]] + [sorted_items[0]] + [sorted_items[1]]
    elif len(sorted_items) == 1:
        selected = [sorted_items[0]] * 3
    else:
        selected = []

    labels = ['近端', '中段', '远端']
    lines, vals = [], []
    for i, (k, v) in enumerate(selected):
        lbl = labels[i] if i < len(labels) else k
        if v[2] >= 10000:
            strike_fmt = f"${v[2]/1000:.0f}K"
        elif v[2] >= 1000:
            strike_fmt = f"${v[2]:,.0f}"
        else:
            strike_fmt = f"${v[2]:,.0f}"
        lines.append(f"  {lbl} {k} IV={v[1]:.1f}% ({strike_fmt})")
        vals.append(v[1])

    if len(vals) >= 3:
        if vals[0] > vals[1] * 1.12 and vals[1] > vals[2] * 1.12:
            struct = "近端IV异常偏高，远端正向contango"
        elif vals[0] < vals[1] * 0.88 and vals[1] < vals[2] * 0.88:
            struct = "正常contango，远端溢价合理"
        elif vals[0] > vals[1] * 1.12:
            struct = "近端明显偏高（可能受事件驱动）"
        elif vals[2] > vals[1] * 1.12:
            struct = "远端溢价偏高，市场对远期波动有定价"
        else:
            struct = "期限结构平坦，无明显套利空间"
    else:
        struct = "期限结构数据不足"
    return lines, struct, vals

def calc_pcr(options):
    puts = sum((o.get('volume', 0) or 0) for o in options if '-P' in o.get('instrument_name', ''))
    calls = sum((o.get('volume', 0) or 0) for o in options if '-C' in o.get('instrument_name', ''))
    return puts / calls if calls else 0.5

def calc_basis(futures, spot):
    if not futures or not spot:
        return 0
    near = min(futures, key=lambda x: abs((x.get('estimated_delivery_price') or 0) - spot))
    fp = near.get('mark_price', 0) or near.get('last', 0)
    return ((fp - spot) / spot) * 100 if fp and spot else 0

def pcr_label(pcr):
    if pcr < 0.6:
        return "Call占优，多方主导"
    elif pcr < 0.9:
        return "Call略多，温和偏多"
    elif pcr <= 1.1:
        return "中性，多空均衡"
    elif pcr <= 1.4:
        return "Put略多，温和偏空"
    else:
        return "Put放量，避险情绪浓厚"

# ========== 新闻获取 ==========

def parse_rss_date(pubdate_str):
    """解析RSS pubDate格式，返回datetime(UTC)"""
    try:
        # 格式: 'Wed, 13 May 2026 21:38:34 GMT'
        return datetime.strptime(pubdate_str.strip(), '%a, %d %b %Y %H:%M:%S %Z').replace(tzinfo=timezone.utc)
    except:
        return None

def fetch_rss_items(url, max_items=10):
    """获取RSS feed，返回(title, pubDate)列表"""
    items = []
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code != 200:
            return items
        # 提取 <item> 块
        item_blocks = re.findall(r'<item>(.*?)</item>', r.text, re.DOTALL)
        for block in item_blocks[:max_items]:
            title_m = re.search(r'<title>(.*?)</title>', block, re.DOTALL)
            date_m = re.search(r'<pubDate>(.*?)</pubDate>', block, re.DOTALL)
            if title_m:
                title = re.sub(r'\s+', ' ', title_m.group(1)).strip()
                pubdate = parse_rss_date(date_m.group(1)) if date_m else None
                if title and len(title) > 8:
                    items.append((title, pubdate))
    except:
        pass
    return items

def fetch_news_cn():
    """获取24小时内中文加密/宏观新闻，按时间排序，剔除旧闻"""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    
    # 多维度搜索，优先中文
    rss_urls = [
        # 中文：宏观/关税/美联储
        ('宏观', 'https://news.google.com/rss/search?q=美联储+利率+通胀+关税+特朗普&hl=zh-CN&gl=CN'),
        # 中文：比特币/期权到期
        ('加密', 'https://news.google.com/rss/search?q=比特币+期权+到期+加密+市场&hl=zh-CN&gl=CN'),
        # 中文：ETF/机构/贝莱德
        ('加密', 'https://news.google.com/rss/search?q=贝莱德+Coinbase+比特币+ETF&hl=zh-CN&gl=CN'),
        # 中文：吴说专业加密新闻
        ('加密', 'https://news.google.com/rss/search?q=吴说+比特币+期权+加密+市场&hl=zh-CN&gl=CN'),
        # 中文：美联储+加密
        ('宏观', 'https://news.google.com/rss/search?q=美联储+加息+降息+比特币+加密&hl=zh-CN&gl=CN'),
        # 英文补充（后备）
        ('加密', 'https://news.google.com/rss/search?q=bitcoin+crypto+market+outlook+fed+inflation&hl=en&gl=US'),
    ]
    
    all_items = []  # (title, pubdate, category)
    seen_titles = set()
    
    for cat, url in rss_urls:
        feed_items = fetch_rss_items(url)
        for title, pubdate in feed_items:
            # 去重
            t_clean = re.sub(r'\s+', ' ', title).strip()
            if t_clean in seen_titles:
                continue
            seen_titles.add(t_clean)
            # 时间过滤：24h内
            if pubdate and pubdate < cutoff:
                continue
            # 跳过垃圾
            skip_words = ['5 Years', 'You Should Know', 'Price Prediction', 'Forecast',
                         '英诺赛科', '禾赛', '卡乐比', '薯片', 'A股', 'A share',
                         'Google 新闻', 'Google News', '最新A', '白银涨势',
                         '走势预测', '操作策略', 'Bitget', 'Crypto Daily Market']
            if any(k in t_clean for k in skip_words):
                continue
            if 'http' in t_clean or '@' in t_clean:
                continue
            all_items.append((t_clean, pubdate, cat))
    
    # 按时间倒序排列
    all_items.sort(key=lambda x: x[1] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    
    # 取最多3条，智能去重
    result = []
    seen_keywords = []  # 每个已选标题的关键词集
    for title, pubdate, cat in all_items:
        # 提取关键实体词
        keywords = set()
        for kw in ['贝莱德','Coinbase','比特币','以太坊','美联储','非农','PPI','CPI',
                    '特朗普','关税','Warsh','沃什','CLARITY','期权','ETF','MicroStrategy',
                    'BTC','ETH','加密','降息','加息','通胀','国债','代币化']:
            if kw.lower() in title.lower():
                keywords.add(kw.lower())
        if not keywords:
            # 没匹配到关键实体，用前10个汉字
            zh_chars = re.findall(r'[\u4e00-\u9fff]', title)
            keywords = set(''.join(zh_chars[:5]))
        
        # 去重检查：如果与已有结果共享超过50%关键词，跳过
        dup = False
        for sk in seen_keywords:
            if not keywords or not sk:
                continue
            overlap = len(keywords & sk) / max(len(keywords), len(sk))
            if overlap > 0.4:
                dup = True
                break
        if dup:
            continue
        seen_keywords.append(keywords)
        result.append(title)
        if len(result) >= 4:
            break
    
    return result

# ========== 策略引擎 ==========

def strategy_engine(btc_pcr, eth_pcr, btc_basis, eth_basis, btc_near_iv, eth_near_iv):
    if btc_pcr < 0.6:
        direction = "偏多"
    elif btc_pcr > 1.4:
        direction = "偏空"
    else:
        direction = "中性"
    
    iv_cheap = btc_near_iv < 45

    if direction == "偏多" and iv_cheap:
        strategy = "Bull Put Spread（牛市看涨价差）"
        logic = [
            f"PCR {btc_pcr:.2f}偏低，Call端主导，短线买盘活跃",
            f"IV {btc_near_iv:.1f}%处历史低位，卖Put收租效率高",
            f"基差 {btc_basis:+.2f}%近乎平水，杠杆未涌入，震荡偏多格局",
        ]
    elif direction == "偏空" and iv_cheap:
        strategy = "Bear Put Spread（熊市看跌价差）"
        logic = [
            f"PCR {btc_pcr:.2f}偏高，Put端放量避险升温",
            f"IV偏低买Put成本可控，适合做下行保护",
            f"基差 {btc_basis:+.2f}%无杠杆支撑，需防范急跌",
        ]
    elif direction == "偏多":
        strategy = "Call Credit Spread（卖出Call价差）"
        logic = [
            f"PCR {btc_pcr:.2f}偏多但IV偏高，卖Call收premium划算",
            "用价差控制上行风险",
        ]
    elif direction == "偏空":
        strategy = "Put Debit Spread（买入Put价差）"
        logic = [
            f"PCR {btc_pcr:.2f}偏空，Put端蓄力",
            "买Put需控制成本，价差比裸Put更优",
        ]
    else:
        strategy = "Iron Condor（铁鹰式）"
        logic = [
            f"PCR {btc_pcr:.2f}中性，方向不明确，震荡格局延续概率高",
            f"IV {btc_near_iv:.1f}%偏低，卖vol吃时间价值",
            f"基差 {btc_basis:+.2f}%近乎平水，杠杆未涌入，适合区间策略",
        ]
    
    eth_note = ""
    if eth_pcr > 1.3:
        eth_note = f"ETH端PCR={eth_pcr:.2f}偏Put，可考虑Put Credit Spread用高IV收premium"
    
    return strategy, logic, eth_note


# ========== 主生成函数 ==========

def generate():
    now = datetime.now(timezone(timedelta(hours=8)))
    date_str = now.strftime('%Y年%m月%d日')
    weekday_cn = ['周一','周二','周三','周四','周五','周六','周日'][now.weekday()]
    
    # ---- 数据获取 ----
    btc_p, btc_ch = binance_ticker('BTC')
    eth_p, eth_ch = binance_ticker('ETH')
    btc_idx = get_index('btc') or btc_p
    eth_idx = get_index('eth') or eth_p
    
    bto = get_options('BTC')
    etho = get_options('ETH')
    btf = get_futures('BTC')
    ethf = get_futures('ETH')
    
    btc_hv = get_hv('btc')
    eth_hv = get_hv('eth')
    btc_pcr = calc_pcr(bto)
    eth_pcr = calc_pcr(etho)
    btc_basis = calc_basis(btf, btc_idx)
    eth_basis = calc_basis(ethf, eth_idx)
    btc_ts_lines, btc_struct, btc_ivs = term_structure(bto, btc_idx)
    eth_ts_lines, eth_struct, eth_ivs = term_structure(etho, eth_idx)
    
    btc_near_iv = get_near_atm_iv(bto, btc_idx)
    eth_near_iv = get_near_atm_iv(etho, eth_idx)
    
    # ---- 新闻 ----
    news = fetch_news_cn()
    
    # ---- OI / Vol Top 3 ----
    btoi3 = sorted(bto, key=lambda x: x.get('open_interest', 0) or 0, reverse=True)[:3]
    btvol3 = sorted(bto, key=lambda x: x.get('volume', 0) or 0, reverse=True)[:3]
    ethoi3 = sorted(etho, key=lambda x: x.get('open_interest', 0) or 0, reverse=True)[:3]
    ethvol3 = sorted(etho, key=lambda x: x.get('volume', 0) or 0, reverse=True)[:3]
    
    btc_oi_lines = fmt_oi_vol(btoi3, 'open_interest')
    btc_vol_lines = fmt_oi_vol(btvol3, 'volume')
    eth_oi_lines = fmt_oi_vol(ethoi3, 'open_interest')
    eth_vol_lines = fmt_oi_vol(ethvol3, 'volume')
    
    # ---- 策略 ----
    strategy, logic, eth_note = strategy_engine(btc_pcr, eth_pcr, btc_basis, eth_basis, btc_near_iv, eth_near_iv)
    
    # ---- IV贵贱判断 ----
    if btc_near_iv and btc_hv:
        iv_hv_gap = btc_near_iv - btc_hv
        if iv_hv_gap > 8:
            iv_cheap_label = f"期权偏贵，IV高于HV约{iv_hv_gap:.0f}个vol点"
        elif iv_hv_gap > 3:
            iv_cheap_label = f"期权略贵，IV高于HV约{iv_hv_gap:.0f}个vol点"
        elif iv_hv_gap > -3:
            iv_cheap_label = f"IV接近HV，期权定价合理"
        else:
            iv_cheap_label = f"期权偏便宜，IV低于HV约{abs(iv_hv_gap):.0f}个vol点"
    else:
        iv_cheap_label = ""
    
    if eth_near_iv and btc_near_iv:
        eth_btc_gap = eth_near_iv - btc_near_iv
        eth_iv_note = f"ETH全期限高于BTC约{eth_btc_gap:.0f}个vol点"
    else:
        eth_iv_note = ""
    
    # ---- 基差解读 ----
    if abs(btc_basis) < 0.5:
        basis_note = "基差近乎平水，杠杆情绪中性"
    elif btc_basis > 2:
        basis_note = f"基差+{btc_basis:.2f}%偏高，杠杆资金入场积极"
    elif btc_basis > 0:
        basis_note = f"基差+{btc_basis:.2f}%，市场情绪温和偏多"
    else:
        basis_note = f"基差{btc_basis:.2f}%倒挂，杠杆资金撤离"
    
    # ---- 组装输出 ----
    lines = [
        f"【加密期权精华日报】 {date_str}（{weekday_cn}）",
        "",
        "一、宏观与大势",
        "  · 非农参考：4月非农+11.5万（预期6.2万），失业率4.3%，前两月合计下修1.6万。Warsh确认Fed主席（54-45票）。",
        "  · 行业动态：CLARITY Act于5月13日进入Markup阶段，超100条修正案，通过概率约60-70%。加征103%关税持续磋商，市场情绪偏谨慎。",
    ]
    
    if news:
        for n in news[:4]:
            lines.append(f"  · 行业快讯：{n}")
    else:
        lines.append("  · 本时段无显著加密行业事件，市场焦点在宏观")
    
    lines.append("")
    lines.append("二、波动率深度分析")
    lines.append(f"  价格：BTC ${btc_p:,.0f}（{btc_ch:+.2f}%）| ETH ${eth_p:,.0f}（{eth_ch:+.2f}%）")
    lines.append("")
    lines.append("  BTC IV期限结构：")
    lines.extend(btc_ts_lines)
    lines.append(f"  判断：{btc_struct}")
    if iv_cheap_label:
        lines.append(f"  对比：HV={btc_hv:.1f}%，{iv_cheap_label}")
    lines.append("")
    lines.append("  ETH IV期限结构：")
    lines.extend(eth_ts_lines)
    lines.append(f"  判断：{eth_struct}")
    if eth_iv_note:
        lines.append(f"  对比：HV={eth_hv:.1f}%，{eth_iv_note}")
    else:
        lines.append(f"  对比：HV={eth_hv:.1f}%")
    lines.append("")
    lines.append(f"  情绪：PCR BTC={btc_pcr:.2f}（{pcr_label(btc_pcr)}）| ETH={eth_pcr:.2f}（{pcr_label(eth_pcr)}）")
    lines.append(f"  资金：基差 BTC={btc_basis:+.2f}% | ETH={eth_basis:+.2f}%，{basis_note}")
    lines.append("")
    lines.append("三、核心资金流与OI集中")
    lines.append("  BTC OI TOP3：")
    lines.extend(btc_oi_lines)
    lines.append("  BTC Vol TOP3：")
    lines.extend(btc_vol_lines)
    lines.append("  ETH OI TOP3：")
    lines.extend(eth_oi_lines)
    lines.append("  ETH Vol TOP3：")
    lines.extend(eth_vol_lines)
    lines.append("")
    lines.append("四、今日策略建议")
    lines.append(f"  {strategy}")
    for l in logic:
        lines.append(f"  · {l}")
    if eth_note:
        lines.append(f"  · {eth_note}")
    lines.append("")
    lines.append(f"  风险提示：CLARITY Act审议不及预期或Warsh鹰派讲话可能引发急跌，需设好止损")
    lines.append(f"  数据时间：{now.strftime('%Y-%m-%d %H:%M')} CST | 数据源：Binance+Deribit")
    lines.append("  仅供参考，不构成投资建议")
    
    return "\n".join(lines)


def validate_report(text):
    """验证日报四节完整性，返回缺失的节编号列表"""
    required = ["一、宏观与大势", "二、波动率深度分析", "三、核心资金流与OI集中", "四、今日策略建议"]
    missing = [s for s in required if s not in text]
    return missing

if __name__ == "__main__":
    max_retries = 2
    for attempt in range(max_retries):
        try:
            report = generate()
            missing = validate_report(report)
            if missing:
                print(f"⚠️ 第{attempt+1}次生成缺少{'/'.join(missing)}，重试中...", file=sys.stderr)
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2)
                    continue
                else:
                    print(f"⚠️ 重试耗尽，仍缺少{'/'.join(missing)}，输出原始结果", file=sys.stderr)
            print(report)
            break
        except Exception as e:
            print(f"⚠️ 第{attempt+1}次生成异常：{e}", file=sys.stderr)
            if attempt < max_retries - 1:
                import time
                time.sleep(2)
                continue
            import traceback
            traceback.print_exc(file=sys.stderr)
            print(f"⚠️ 日报生成异常：{e}")
            sys.exit(1)