# Deribit DDH (Delta Dynamic Hedging)

实时Delta动态对冲工具，监控ETH期权+永续组合的净Delta，超死区自动通过永续合约配平。

## 模式
- **REST (cron)**: 每8小时轮询检查
- **WS (实时)**: WebSocket常驻，秒级监控

## 参数
- 死区: ±5.0 ETH
- 单笔上限: 5.0 ETH（超量自动分批）
- 冷却: 30分钟

## 使用
```bash
# REST模式
python3 scripts/deribit-ddh.py

# WS实时模式
python3 scripts/deribit-ddh.py --ws

# 仿真
python3 scripts/deribit-ddh.py --dry
```
