#!/usr/bin/env python3
"""
deribit-ETH-DDH-skill — Deribit Delta Dynamic Hedging for ETH options

Monitors net delta (options + perpetuals) on Deribit and automatically
hedges ETH-PERPETUAL when delta exceeds the dead zone.

Key concepts:
- delta_total (from get_account_summary) = net delta including options + perpetuals
- ETH-PERPETUAL = coin-margined perpetual; amount param = number of contracts
- 1 contract ≈ 1/index_price ETH ≈ $1 notional value
- Hedge size = int(|delta_total| × index_price) contracts
"""

import os, sys, json, time, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# --- Configuration ---
DEAD = 1.0       # Dead zone (ETH). Net delta within ±DEAD → no action.
GAP = 30         # Cooldown interval (minutes)
MAX = 5.0        # Max single hedge amount (ETH)
ALERT = 50.0     # Total exposure alert threshold (ETH)
CUR = "ETH"      # Currency
HD = "ETH-PERPETUAL"  # Hedge instrument

# Load env vars for API credentials
load_env = True
try:
    from dotenv import load_dotenv
except ImportError:
    load_env = False

_script_dir = Path(__file__).parent
_env_file = _script_dir / ".env"
if load_env and _env_file.exists():
    load_dotenv(_env_file)

# Deribit API
TESTNET = os.getenv("DDH_TESTNET", "true").lower() == "true"
API_URL = "https://test.deribit.com/api/v2" if TESTNET else "https://www.deribit.com/api/v2"
CLIENT_ID = os.getenv("DERIBIT_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("DERIBIT_CLIENT_SECRET", "")

# State file for cooldown tracking
STATE_FILE = Path(os.getenv("DDH_STATE_FILE", str(_script_dir / "data" / "ddh-state.json")))


def log(msg):
    """Print timestamped log to stderr."""
    t = datetime.now(timezone(timedelta(hours=8))).strftime("%m-%d %H:%M:%S")
    print(f"[{t}] {msg}", flush=True, file=sys.stderr)


class DeribitClient:
    """Minimal Deribit JSON-RPC client."""

    def __init__(self):
        self.token = None
        self.expires = 0

    def _request(self, method, params=None):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        resp = requests.post(
            API_URL,
            json={
                "jsonrpc": "2.0",
                "id": int(time.time() * 1000) % 1_000_000,
                "method": method,
                "params": params or {},
            },
            headers=headers,
            timeout=15,
        ).json()
        if resp.get("error"):
            raise Exception(
                f"{method}: [{resp['error'].get('code', '?')}] "
                f"{resp['error'].get('message', '?')}"
            )
        return resp["result"]

    def _auth(self):
        if not self.token or time.time() >= self.expires:
            result = self._request("public/auth", {
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            })
            self.token = result["access_token"]
            self.expires = time.time() + result["expires_in"] - 60

    def get_account_summary(self):
        self._auth()
        return self._request("private/get_account_summary", {"currency": CUR})

    def get_positions(self, kind):
        self._auth()
        result = self._request("private/get_positions", {
            "currency": CUR, "kind": kind
        })
        return result if isinstance(result, list) else []

    def get_index_price(self):
        return self._request("public/get_index_price", {
            "index_name": "eth_usd"
        }).get("index_price", 0)

    def place_market_order(self, side, eth_amount, index_price):
        """Place market order on ETH-PERPETUAL.
        
        Args:
            side: 'buy' or 'sell'
            eth_amount: amount in ETH
            index_price: current index price
            
        Returns:
            dict with order details or None if size < 1 contract
        """
        self._auth()
        contracts = int(eth_amount * index_price)  # ETH → contracts
        if contracts < 1:
            return None

        method = "private/buy" if side == "buy" else "private/sell"
        result = self._request(method, {
            "instrument_name": HD,
            "amount": contracts,
            "type": "market",
        })
        order = result.get("order", result)
        return {
            "side": side,
            "eth": eth_amount,
            "contracts": contracts,
            "filled": order.get("filled_amount", 0),
            "avg_price": order.get("average_price", 0),
        }


def parse_options(positions):
    """Extract greeks from option positions."""
    parsed = []
    for p in positions:
        size = float(p.get("size", 0) or 0)
        if size == 0:
            continue
        name = p.get("instrument_name", "")
        parts = name.split("-")
        parsed.append({
            "expiry": parts[1] if len(parts) >= 2 else "",
            "strike": int(parts[2]) if len(parts) >= 4 and parts[2].isdigit() else 0,
            "option_type": parts[3] if len(parts) >= 4 else "?",
            "size": size,
            "direction": p.get("direction", "buy"),
            "delta": float(p.get("delta", 0)),
            "gamma": float(p.get("gamma", 0)),
            "vega": float(p.get("vega", 0)),
            "theta": float(p.get("theta", 0)),
        })
    return parsed


def panel(timestamp, index_price, greeks, option_positions,
          perp_contracts, perp_eth, action=None, delta_after=None):
    """Generate a formatted data panel for output."""
    net_delta = greeks["delta"]
    nd_after = delta_after if delta_after is not None else net_delta

    lines = []
    lines.append("=" * 36)
    lines.append(f"DDH Data Panel  {timestamp}")
    lines.append("=" * 36)
    lines.append("")
    lines.append(f"{'Item':<20} {'Value'}")
    lines.append(f"{'─'*20} {'─'*20}")
    lines.append(f"{'ETH Price':<20} ${index_price:.0f}")
    status = "✅ In dead zone" if abs(net_delta) <= DEAD else "⚠️ Exceeds dead zone"
    lines.append(f"{'Net Delta':<20} {net_delta:+.4f} ETH  {status}")
    lines.append(f"{'Gamma':<20} {greeks['gamma']:+.4f}")
    lines.append(f"{'Vega':<20} {greeks['vega']:+.2f}")
    lines.append(f"{'Theta':<20} {greeks['theta']:+.2f}")
    if delta_after is not None and delta_after != net_delta:
        lines.append(f"{'After Delta':<20} {nd_after:+.4f} ETH")
    lines.append("")

    lines.append("Positions:")
    for d in option_positions:
        lbl = "SHORT" if d["direction"] == "sell" else "LONG"
        lines.append(
            f"  {lbl} {d['expiry']} {d['strike']}{d['option_type']} "
            f"×{int(abs(d['size']))}  Δ{d['delta']:+.2f}"
        )
    perp_side = "LONG" if perp_contracts > 0 else ("SHORT" if perp_contracts < 0 else "NONE")
    lines.append(f"  {HD}: {perp_side} {abs(perp_contracts):,.0f} contracts "
                 f"(≈{abs(perp_eth):.2f} ETH)")
    lines.append("")

    lines.append("Conclusion:")
    if abs(nd_after) <= DEAD:
        lines.append(
            f"  Net Delta {nd_after:+.4f} ETH within ±{DEAD} ETH dead zone. "
            f"No hedge needed."
        )
    else:
        lines.append(
            f"  Net Delta {nd_after:+.4f} ETH exceeds ±{DEAD} ETH dead zone. "
            f"Hedge {abs(nd_after):.4f} ETH ≈ {int(abs(nd_after) * index_price)} contracts."
        )
    if abs(net_delta) > ALERT:
        lines.append(f"  🚨 Total exposure exceeds {ALERT} ETH threshold!")

    if action:
        if action.get("dry_run"):
            lines.append(
                f"  [Dry-run] Would {'SELL' if action['side'] == 'sell' else 'BUY'} "
                f"{action['eth']:.4f} ETH ({action['contracts']} contracts)"
            )
        else:
            avg = action.get("avg_price", 0) or 0
            lbl = "SHORT" if action["side"] == "sell" else "LONG"
            lines.append(
                f"  [Executed] {lbl} {action['eth']:.4f} ETH @ ${avg:.1f} "
                f"({action['contracts']} contracts)"
            )

    lines.append("")
    lines.append("=" * 36)
    return "\n".join(lines)


def main():
    """Main DDH loop."""
    dry_run = "--dry" in sys.argv
    force = "--force" in sys.argv  # Skip cooldown & MAX limit

    timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%m-%d %H:%M")

    if not CLIENT_ID or not CLIENT_SECRET:
        log("ERROR: DERIBIT_CLIENT_ID / DERIBIT_CLIENT_SECRET not set")
        return

    client = DeribitClient()

    try:
        # Fetch data
        index_price = client.get_index_price()
        log(f"ETH ${index_price:.2f}")

        acct = client.get_account_summary()
        greeks = {
            "delta": float(acct.get("delta_total", 0) or 0),
            "gamma": float(acct.get("options_gamma", 0) or 0),
            "vega": float(acct.get("options_vega", 0) or 0),
            "theta": float(acct.get("options_theta", 0) or 0),
        }

        option_positions = parse_options(client.get_positions("option"))

        perp_positions = [
            p for p in client.get_positions("future")
            if "PERPETUAL" in p.get("instrument_name", "")
        ]
        perp_contracts = sum(float(p.get("size", 0) or 0) for p in perp_positions)
        perp_eth = sum(float(p.get("size_currency", 0) or 0) for p in perp_positions)

        net_delta = greeks["delta"]
        log(f"Net Delta={net_delta:+.4f} ETH  Perpetual={perp_eth:+.4f} ETH "
            f"({perp_contracts:.0f} contracts)")

        # Cooldown check
        skip = False
        if abs(net_delta) > DEAD and not force and STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
                elapsed = (time.time() - state.get("t", 0)) / 60
                if elapsed < GAP:
                    log(f"Cooldown active ({elapsed:.0f}/{GAP} min)")
                    skip = True
            except Exception:
                pass

        action = None
        delta_after = None

        if abs(net_delta) > DEAD and not skip:
            eth_amount = abs(net_delta)
            if not force and eth_amount > MAX:
                eth_amount = MAX
                log(f"Capped at {eth_amount:.4f} ETH (≤ {MAX} ETH)")

            contracts = int(eth_amount * index_price)
            if contracts < 1:
                log(f"Hedge too small: {eth_amount:.4f} ETH × ${index_price:.0f} = {contracts} contracts")
            else:
                side = "sell" if net_delta > 0 else "buy"

                if dry_run:
                    action = {
                        "side": side, "eth": eth_amount,
                        "contracts": contracts, "dry_run": True,
                    }
                else:
                    result = client.place_market_order(side, eth_amount, index_price)
                    if result and result.get("filled", 0) > 0:
                        action = result
                        time.sleep(1)
                        acct2 = client.get_account_summary()
                        delta_after = float(acct2.get("delta_total", 0) or 0)
                        log(f"Post-hedge Net Delta={delta_after:+.4f}")

                        # Save cooldown timestamp (only for cron, not force)
                        if not force:
                            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                            STATE_FILE.write_text(json.dumps({"t": time.time()}))

        # Always output the data panel
        output = panel(
            timestamp, index_price, greeks,
            option_positions, perp_contracts, perp_eth,
            action, delta_after,
        )
        print(output)

    except Exception as e:
        log(f"Error: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    main()