# Deribit Public API Reference

## Base URL
https://www.deribit.com/api/v2

All endpoints use JSON-RPC 2.0 (POST). No authentication required.

## Endpoints Used

### public/get_index_price
Get spot index price.
- Params: `{"index_name": "btc_usd" | "eth_usd"}`
- Returns: `{"index_price": float}`

### public/get_book_summary_by_currency
Get options/futures full data for a currency.
- Params: `{"currency": "BTC"|"ETH", "kind": "option"|"future"}`
- Returns: array of instruments with mark_iv, volume, open_interest, instrument_name, etc.

### public/get_historical_volatility
Get HV time series (daily).
- Params: `{"currency": "BTC"|"ETH"}`
- Returns: `[[timestamp, value], ...]`

### public/get_volatility_index_data
Get DVOL historical OHLC data.
- Params: `{"currency": "BTC"|"ETH", "start_timestamp": ms, "end_timestamp": ms, "resolution": "1D"}`
- Returns: `{"data": [[timestamp, open, high, low, close], ...]}`
- Resolution options: 1M, 5M, 15M, 1H, 4H, 1D, 1W

## Rate Limits
- Public endpoints: 20 requests/second
- No API key required
