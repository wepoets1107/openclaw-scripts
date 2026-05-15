# 加密期权精华日报

每日8:00自动生成，从Binance/Deribit公共API拉取数据，输出BTC/ETH期权市场全景。

## 数据源
- Binance: 现货价格
- Deribit: IV期限结构、OI/Vol TOP3、PCR、基差、HV
- Google News RSS: 24h加密/宏观新闻

## 输出
四部分：宏观大势 → 波动率深度 → 资金流OI集中 → 策略建议

## 使用
```bash
python3 scripts/crypto-options-daily.py
```
