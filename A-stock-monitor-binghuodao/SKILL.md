---
name: A-stock-monitor-binghuodao
description: >
  A股ETF期权信号监测。基于akshare公共数据源（上交所/深交所PCR、QVIX波动率指数、OI/成交量统计），
  无需API密钥。覆盖6个标的：上证50ETF、沪深300ETF、中证500ETF、科创50ETF、创业板ETF、深证100ETF。
  输出QVIX分位评估、PCR情绪判断、沽购OI比、策略建议。支持历史数据回测（--date参数）。
  触发词：A股期权、ETF期权信号、QVIX、PCR、期权监测、A股波动率、A股期权策略。
  Triggers: A股期权, ETF期权, QVIX, PCR, A-share options, China options monitor.
---

# A股ETF期权信号监测

基于akshare公共数据源，零API密钥，覆盖6大ETF期权标的。

## 运行

```bash
python3 {baseDir}/scripts/monitor.py [--date YYYYMMDD] [--etf 50|300|500|kcb|cyb|sz100]
```

参数说明：
- --date: 交易日期，默认最近交易日，周末自动回退至周五，支持历史回测
- --etf: 指定标的，不填则输出全部6个

## 标的列表

| 代码 | 名称 | 交易所 | QVIX |
|------|------|--------|------|
| 50 | 上证50ETF | SSE | ✅ |
| 300 | 沪深300ETF | SSE | ✅ |
| 500 | 中证500ETF | SSE | ✅ |
| kcb | 科创50ETF | SSE | ✅ |
| cyb | 创业板ETF | SZSE | ✅ |
| sz100 | 深证100ETF | SZSE | ❌ |

## 输出内容

每个标的输出：
1. QVIX当前值 + 30日均值/区间/分位 + 期权贵贱评估
2. PCR（认沽/认购比率）+ 情绪判断（恐慌/正常/过度乐观）
3. OI总量 + 认购/认沽分项 + 沽购比
4. 成交量 + 认购/认沽分项
5. 策略建议（基于QVIX+PCR+OI三维度推导）

## 阈值配置

- PCR > 1.2：恐慌区间
- PCR < 0.6：过度乐观
- QVIX分位 > 80%：期权偏贵
- QVIX分位 < 20%：期权偏便宜

## 数据源

详见 references/data-sources.md

## 依赖

akshare（pip install akshare）

## 输出格式

纯文本，适配微信/Telegram等不渲染markdown的平台。
