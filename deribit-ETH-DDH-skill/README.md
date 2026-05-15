# Deribit DDH (Delta Dynamic Hedging)

## 概述
实时Delta动态对冲工具，监控ETH期权+永续组合的净Delta，超死区自动通过永续合约配平。

## 核心参数
| 参数 | 值 | 说明 |
|------|-----|------|
| 死区 | ±5.0 ETH | 死区范围内不触发对冲 |
| 单笔上限 | 5.0 ETH | 超过自动拆分多笔 |
| 冷却 | 30分钟 | 对冲后冷却期 |

## 运行模式

### REST模式 (cron)
```bash
python3 deribit-ddh.py
```

### WS实时模式 (常驻)
```bash
python3 deribit-ddh.py --ws
```
WebSocket实时监控，秒级检测delta变化，断线自动重连。

### 仿真模式
```bash
python3 deribit-ddh.py --dry
python3 deribit-ddh.py --ws --dry
```

### 跳过冷却和限额 (岛主手动)
```bash
python3 deribit-ddh.py --force
```

## 配置
复制 `.env.example` 为 `.env` 并填入 Deribit API Key：
```
DERIBIT_CLIENT_ID=your_id
DERIBIT_CLIENT_SECRET=your_secret
DDH_TESTNET=true   # 测试网=true, 实盘=false
```

## 输出示例
```
🦐 DDH 数据面板  05-15 08:30
====================================
| ETH 价格 | $2292 |
| Net Delta | -0.6313 ETH ✅ 死区内 |
| Gamma | -0.1022 |
| Vega | -370.92 |
| Theta | +261.63 |
====================================
```

## 更新记录
- 2026-05-15: 新增WS实时模式，分批对冲逻辑，死区改为±5.0
- 2026-05-14: 初始版本
