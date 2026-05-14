# Deribit ETH DDH Skill 🦐

**Delta Dynamic Hedging** for ETH options on Deribit.

Monitors net delta (options + perpetual swap positions) and automatically hedges
exposure using **ETH-PERPETUAL** when the net delta exceeds the dead zone.

## How It Works

1. Fetches account summary + positions from Deribit API
2. Computes net delta = `delta_total` from `get_account_summary` (includes all options + perpetuals)
3. If `|net_delta| > DEAD` (default ±1.0 ETH):
   - Places a market order on `ETH-PERPETUAL` in the opposite direction
   - Applies cooldown (30 min) and MAX limit (5.0 ETH) unless `--force` is used
4. Always prints a formatted data panel with full Greeks, positions, and action taken

## Usage

```bash
# Install dependencies
pip install python-dotenv requests

# Setup credentials
cp .env.example .env
# Edit .env with your Deribit API credentials

# Dry-run (preview only, no orders)
python3 deribit-ddh.py --dry

# Execute (with cooldown + MAX limit)
python3 deribit-ddh.py

# Force execution (skip cooldown & MAX limit)
python3 deribit-ddh.py --force
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEAD` | 1.0 | Dead zone in ETH (no action if `\|delta\| ≤ DEAD`) |
| `GAP` | 30 | Cooldown interval in minutes |
| `MAX` | 5.0 | Max single hedge amount in ETH |
| `ALERT` | 50.0 | Total exposure alert threshold |
| `DDH_TESTNET` | `true` | Use `test.deribit.com` (set to `false` for mainnet) |

## Key Concepts

- `delta_total` from Deribit's `get_account_summary` already includes options + perpetuals
- `ETH-PERPETUAL` is coin-margined: 1 contract ≈ 1/index_price ETH ≈ $1 notional
- Hedge size in contracts = `int(|delta| × index_price)`

## Output Example

```
====================================
DDH Data Panel  05-14 21:48
====================================

Item                           Value
────────────────────           ────────────────────
ETH Price                      $2256
Net Delta                      +0.2461 ETH  ✅ In dead zone
Gamma                          -0.1044
Vega                           -340.30
Theta                          +216.97

Positions:
  SHORT 26JUN26 1900P ×70  Δ+11.39
  SHORT 26JUN26 2700C ×100 Δ-18.56
  ETH-PERPETUAL: LONG 10,001 contracts (≈4.43 ETH)

Conclusion:
  Net Delta +0.2461 ETH within ±1.0 ETH dead zone. No hedge needed.

====================================
```

## License

MIT-0