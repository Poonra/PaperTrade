import os
import csv
import yaml
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

load_dotenv()

with open("config.yaml") as f:
    CONFIG = yaml.safe_load(f)

LOGS_DIR = Path("logs")
TRADES_CSV = LOGS_DIR / "trades.csv"
PORTFOLIO_CSV = LOGS_DIR / "portfolio.csv"

TRADES_FIELDS = ["timestamp", "symbol", "action", "qty", "price", "value", "rationale", "order_id"]
PORTFOLIO_FIELDS = ["date", "portfolio_value", "cash", "spy_close"]


def _ensure_csv(path: Path, fields: list[str]) -> None:
    if not path.exists():
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()


def _data_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(
        api_key=os.getenv(CONFIG["api"]["alpaca_key_env"]),
        secret_key=os.getenv(CONFIG["api"]["alpaca_secret_env"]),
    )


def _get_spy_close() -> float | None:
    """Fetch the most recent SPY closing price."""
    try:
        client = _data_client()
        from datetime import timedelta
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        req = StockBarsRequest(
            symbol_or_symbols="SPY",
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            limit=1,
            feed=DataFeed.IEX,
        )
        bars = client.get_stock_bars(req)
        spy_bars = bars.data.get("SPY", [])
        return float(spy_bars[-1].close) if spy_bars else None
    except Exception:
        return None


# ── Write functions ────────────────────────────────────────────────────────────

def log_trades(executed: list[dict], quotes: dict) -> None:
    """Append executed orders to trades.csv."""
    _ensure_csv(TRADES_CSV, TRADES_FIELDS)
    now = datetime.now(timezone.utc).isoformat()
    with open(TRADES_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADES_FIELDS)
        for t in executed:
            if t.get("status") != "executed":
                continue
            sym = t.get("symbol", "")
            price = quotes.get(sym, {}).get("mid", 0)
            notional = t.get("notional") or (t.get("qty", 0) * price)
            qty = t.get("qty") or (notional / price if price else 0)
            writer.writerow({
                "timestamp": now,
                "symbol": sym,
                "action": t.get("side", "").upper(),
                "qty": round(qty, 6),
                "price": round(price, 4),
                "value": round(notional, 2),
                "rationale": t.get("rationale", ""),
                "order_id": t.get("order_id", ""),
            })


def log_portfolio_snapshot(account: dict) -> None:
    """Append today's portfolio value and SPY close to portfolio.csv."""
    _ensure_csv(PORTFOLIO_CSV, PORTFOLIO_FIELDS)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Avoid duplicate entries for the same date
    if PORTFOLIO_CSV.exists():
        with open(PORTFOLIO_CSV, "r") as f:
            rows = list(csv.DictReader(f))
        if rows and rows[-1]["date"] == today:
            return

    spy_close = _get_spy_close()
    with open(PORTFOLIO_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PORTFOLIO_FIELDS)
        writer.writerow({
            "date": today,
            "portfolio_value": round(account["portfolio_value"], 2),
            "cash": round(account["cash"], 2),
            "spy_close": spy_close if spy_close else "",
        })


# ── Performance summary ────────────────────────────────────────────────────────

def get_performance_summary(account: dict) -> dict:
    """
    Compute overall performance vs SPY since the first portfolio snapshot.

    Returns a dict ready to format into a Telegram message.
    """
    _ensure_csv(PORTFOLIO_CSV, PORTFOLIO_FIELDS)
    _ensure_csv(TRADES_CSV, TRADES_FIELDS)

    with open(PORTFOLIO_CSV, "r") as f:
        port_rows = list(csv.DictReader(f))

    with open(TRADES_CSV, "r") as f:
        trade_rows = list(csv.DictReader(f))

    current_value = account["portfolio_value"]
    start_value = float(port_rows[0]["portfolio_value"]) if port_rows else current_value
    start_spy = float(port_rows[0]["spy_close"]) if port_rows and port_rows[0]["spy_close"] else None
    current_spy = _get_spy_close()

    portfolio_return_pct = ((current_value - start_value) / start_value) * 100 if start_value else 0

    spy_return_pct = None
    if start_spy and current_spy:
        spy_return_pct = ((current_spy - start_spy) / start_spy) * 100

    alpha = None
    if spy_return_pct is not None:
        alpha = portfolio_return_pct - spy_return_pct

    total_trades = len(trade_rows)
    buys = [t for t in trade_rows if t["action"] == "BUY"]
    sells = [t for t in trade_rows if t["action"] == "SELL"]

    return {
        "current_value": round(current_value, 2),
        "start_value": round(start_value, 2),
        "portfolio_return_pct": round(portfolio_return_pct, 2),
        "spy_return_pct": round(spy_return_pct, 2) if spy_return_pct is not None else None,
        "alpha_pct": round(alpha, 2) if alpha is not None else None,
        "total_trades": total_trades,
        "total_buys": len(buys),
        "total_sells": len(sells),
        "days_tracked": len(port_rows),
    }


if __name__ == "__main__":
    from data import get_account, get_positions
    import json

    account = get_account()
    positions = get_positions()

    print("Logging portfolio snapshot...")
    log_portfolio_snapshot(account)

    print("\n=== PERFORMANCE SUMMARY ===")
    summary = get_performance_summary(account)
    print(json.dumps(summary, indent=2))

    print("\n=== TRADE LOG ===")
    if TRADES_CSV.exists():
        with open(TRADES_CSV) as f:
            print(f.read())
    else:
        print("  No trades logged yet.")
