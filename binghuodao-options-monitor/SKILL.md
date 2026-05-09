---
name: binghuodao-options-monitor
description: >
  Crypto options market intelligence powered by Deribit public API (no API key needed).
  Three modules: (1) Options Daily Report — IV term structure, HV vs IV, OI/Volume ranking,
  futures basis, strategy recommendations; (2) Signal Monitor — IV anomalies, large order detection,
  PCR extremes, basis sentiment; (3) DVOL Snapshot — real-time DVOL index data for BTC and ETH.
  Triggers: 期权日报, 加密期权, Deribit, DVOL, IV期限结构, 期权信号, PCR, 基差, 大单异动,
  options daily, crypto options, volatility monitor, options signal.
---

# Binghuodao Options Monitor

Crypto options intelligence using Deribit public API exclusively. No API key required.

## Modules

### 1. Options Daily Report

Generate a comprehensive daily report:

```bash
python3 {baseDir}/scripts/daily_report.py [btc|eth|all]
```

Output: plain-text daily report with macro context, IV analysis, OI/Volume tables, basis, and strategy.

### 2. Signal Monitor

Detect anomalies and alert-worthy conditions:

```bash
python3 {baseDir}/scripts/signal_monitor.py [btc|eth|all]
```

Detects: IV term structure inversions, large orders (≥1000 contracts), PCR extremes (>1.2 or <0.6), basis anomalies.

### 3. DVOL Snapshot

Real-time DVOL (Deribit Volatility Index) data:

```bash
python3 {baseDir}/scripts/dvol_snapshot.py [btc|eth|all]
```

Output: current DVOL, 24h change, historical percentiles (1d/7d/30d).

## API Reference

All data from Deribit public API v2 (`https://www.deribit.com/api/v2`):

| Endpoint | Purpose |
|----------|---------|
| `public/get_index_price` | Spot index price |
| `public/get_book_summary_by_currency` | Options/futures full data |
| `public/get_historical_volatility` | HV time series |
| `public/get_volatility_index_data` | DVOL historical OHLC data |

No authentication needed. Rate limit: 20 req/s (public endpoints).

## Output Format

All output is **plain text** (no markdown). Suitable for WeChat, Telegram, and other messaging platforms that don't render markdown.
