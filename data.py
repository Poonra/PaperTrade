import os
import yaml
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

load_dotenv()

with open("config.yaml") as f:
    CONFIG = yaml.safe_load(f)


def _trading_client() -> TradingClient:
    return TradingClient(
        api_key=os.getenv(CONFIG["api"]["alpaca_key_env"]),
        secret_key=os.getenv(CONFIG["api"]["alpaca_secret_env"]),
        paper=True,
    )


def _data_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(
        api_key=os.getenv(CONFIG["api"]["alpaca_key_env"]),
        secret_key=os.getenv(CONFIG["api"]["alpaca_secret_env"]),
    )


def get_account() -> dict:
    """Return cash, equity, and buying power from the paper account."""
    client = _trading_client()
    acct = client.get_account()
    return {
        "cash": float(acct.cash),
        "equity": float(acct.equity),
        "buying_power": float(acct.buying_power),
        "portfolio_value": float(acct.portfolio_value),
    }


def get_positions() -> list[dict]:
    """Return all open positions with symbol, qty, market value, and P&L."""
    client = _trading_client()
    positions = client.get_all_positions()
    return [
        {
            "symbol": p.symbol,
            "qty": float(p.qty),
            "avg_entry_price": float(p.avg_entry_price),
            "current_price": float(p.current_price),
            "market_value": float(p.market_value),
            "unrealized_pl": float(p.unrealized_pl),
            "unrealized_plpc": float(p.unrealized_plpc),
        }
        for p in positions
    ]


def get_latest_quotes(symbols: list[str]) -> dict[str, dict]:
    """Return the latest bid/ask/price for each symbol."""
    client = _data_client()
    req = StockLatestQuoteRequest(symbol_or_symbols=symbols, feed=DataFeed.IEX)
    quotes = client.get_stock_latest_quote(req)
    result = {}
    for sym, q in quotes.items():
        mid = (q.bid_price + q.ask_price) / 2 if q.bid_price and q.ask_price else q.ask_price
        result[sym] = {
            "bid": float(q.bid_price or 0),
            "ask": float(q.ask_price or 0),
            "mid": float(mid or 0),
        }
    return result


def get_price_bars(symbols: list[str], days: int = 10) -> dict[str, list[dict]]:
    """Return daily OHLCV bars for the past `days` calendar days per symbol."""
    client = _data_client()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days + 5)  # buffer for weekends/holidays
    result = {}
    for sym in symbols:
        try:
            req = StockBarsRequest(
                symbol_or_symbols=sym,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
                limit=days,
                feed=DataFeed.IEX,
            )
            bars = client.get_stock_bars(req)
            sym_bars = bars.data.get(sym, [])
            result[sym] = [
                {
                    "date": b.timestamp.strftime("%Y-%m-%d"),
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": int(b.volume),
                }
                for b in sym_bars
            ]
        except Exception:
            result[sym] = []
    return result


def get_market_snapshot() -> dict:
    """
    Aggregate everything the analyst needs in one call:
    account state, open positions, latest quotes, and recent bars
    for the full watchlist.
    """
    watchlist = CONFIG["watchlist"]
    return {
        "account": get_account(),
        "positions": get_positions(),
        "quotes": get_latest_quotes(watchlist),
        "bars": get_price_bars(watchlist, days=10),
        "watchlist": watchlist,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import json
    snapshot = get_market_snapshot()
    print(json.dumps(snapshot, indent=2))
