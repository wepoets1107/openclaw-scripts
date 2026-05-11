# ETF走势分析 (创业板 & 科创板)

每日A股收盘后，自动生成创业板ETF和科创板50ETF的走势分析报告。

## 功能
- 价格与趋势（均线形态、周涨跌）
- 波动率画像（HV vs QVIX，IV溢价判断）
- 资金与情绪（成交额、净流入、量价背离）
- 关键价位（支撑/压力）
- 策略方向提示

## 数据源
- 灵犀API（实时行情+资金流）→ 需授权
- 腾讯K线（历史数据+均线+HV）
- akshare（QVIX波动率指数）

## 用法
```bash
python3 etf-trend-analysis.py
```

## 依赖
```
pip install numpy requests akshare
```

## 灵犀授权
首次使用需完成灵犀Skill授权（扫码绑定API Key）。
详见: https://github.com/wepoets1107/openclaw-scripts/tree/main/etf-trend-analysis
