# 数据源说明

## akshare公共接口（无需API密钥）

### 上交所（SSE）
| 函数 | 用途 | 参数 |
|------|------|------|
| index_option_50etf_qvix | 上证50ETF QVIX | 无 |
| index_option_300etf_qvix | 沪深300ETF QVIX | 无 |
| index_option_500etf_qvix | 中证500ETF QVIX | 无 |
| index_option_kcb_qvix | 科创50ETF QVIX | 无 |
| option_daily_stats_sse | SSE期权PCR/OI统计 | date='YYYYMMDD' |

### 深交所（SZSE）
| 函数 | 用途 | 参数 |
|------|------|------|
| index_option_cyb_qvix | 创业板ETF QVIX | 无 |
| option_daily_stats_szse | SZSE期权PCR/OI统计 | date='YYYYMMDD' |

### 注意事项
- QVIX数据有1-2个交易日延迟
- 深证100ETF无QVIX数据
- PCR字段为百分比形式，需÷100转为比率
- 周末可用历史日期回测
- option_risk_indicator_sse 逐合约IV/Greeks数据较慢，本脚本未使用
