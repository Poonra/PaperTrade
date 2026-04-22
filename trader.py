import os
import yaml
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, ClosePositionRequest
from alpaca.trading.enums import OrderSide, TimeInForce

load_dotenv()

with open("config.yaml") as f:
    CONFIG = yaml.safe_load(f)


def _trading_client() -> TradingClient:
    return TradingClient(
        api_key=os.getenv(CONFIG["api"]["alpaca_key_env"]),
        secret_key=os.getenv(CONFIG["api"]["alpaca_secret_env"]),
        paper=True,
    )


def _submit_notional_buy(client: TradingClient, symbol: str, notional: float) -> dict:
    req = MarketOrderRequest(
        symbol=symbol,
        notional=round(notional, 2),
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(req)
    return {
        "order_id": str(order.id),
        "symbol": order.symbol,
        "notional": notional,
        "side": "buy",
        "status": order.status.value,
    }


def _close_position(client: TradingClient, symbol: str) -> dict:
    order = client.close_position(symbol)
    return {
        "order_id": str(order.id),
        "symbol": order.symbol,
        "qty": float(order.qty or 0),
        "side": "sell",
        "status": order.status.value,
    }


# ── Stop loss scanner ──────────────────────────────────────────────────────────

def check_stop_losses(account: dict, positions: list[dict], quotes: dict) -> list[dict]:
    stop_pct = CONFIG["risk"]["stop_loss_pct"]
    client = _trading_client()
    executed = []

    for p in positions:
        loss_pct = p["unrealized_plpc"]
        if loss_pct <= -stop_pct:
            try:
                order = _close_position(client, p["symbol"])
                order["trigger"] = "stop_loss"
                order["loss_pct"] = round(loss_pct * 100, 2)
                executed.append(order)
                print(f"[STOP LOSS] {p['symbol']} loss={loss_pct*100:.2f}% — position closed")
            except Exception as e:
                print(f"[STOP LOSS ERROR] {p['symbol']}: {e}")

    return executed


# ── Execute Claude's recommendations ──────────────────────────────────────────

def execute_trades(
    recommendations: list[dict],
    account: dict,
    positions: list[dict],
    quotes: dict,
) -> list[dict]:
    risk = CONFIG["risk"]
    client = _trading_client()
    results = []
    executed_count = 0

    for trade in recommendations:
        action = trade.get("action", "").upper()
        symbol = trade.get("symbol", "")
        rationale = trade.get("rationale", "")

        if action == "HOLD":
            results.append({"action": "HOLD", "symbol": symbol, "status": "skipped", "rationale": rationale})
            continue

        if executed_count >= risk["max_trades_per_run"]:
            results.append({
                "action": action, "symbol": symbol,
                "status": "rejected", "reason": "max_trades_per_run limit reached",
            })
            continue

        try:
            if action == "BUY":
                notional = float(trade.get("notional", 0))

                if notional < risk["min_trade_value"]:
                    results.append({"action": action, "symbol": symbol, "status": "rejected",
                                    "reason": f"notional ${notional:.2f} below minimum ${risk['min_trade_value']}"})
                    continue

                if notional > account["buying_power"]:
                    results.append({"action": action, "symbol": symbol, "status": "rejected",
                                    "reason": f"insufficient buying power (${account['buying_power']:.2f})"})
                    continue

                order = _submit_notional_buy(client, symbol, notional)
                order["rationale"] = rationale
                order["status"] = "executed"
                results.append(order)
                executed_count += 1
                print(f"[EXECUTED] BUY ${notional:.2f} of {symbol}")

            elif action == "SELL":
                held = next((p for p in positions if p["symbol"] == symbol), None)
                if not held:
                    results.append({"action": action, "symbol": symbol, "status": "rejected",
                                    "reason": f"no open position in {symbol}"})
                    continue

                order = _close_position(client, symbol)
                order["rationale"] = rationale
                order["status"] = "executed"
                results.append(order)
                executed_count += 1
                print(f"[EXECUTED] SELL (close) {symbol}")

            else:
                results.append({"action": action, "symbol": symbol, "status": "rejected",
                                "reason": f"unknown action '{action}'"})

        except Exception as e:
            results.append({"action": action, "symbol": symbol, "status": "error", "reason": str(e)})
            print(f"[ERROR] {action} {symbol}: {e}")

    return results


if __name__ == "__main__":
    from data import get_market_snapshot

    snapshot = get_market_snapshot()
    account = snapshot["account"]
    positions = snapshot["positions"]
    quotes = snapshot["quotes"]

    print("Account:", account)
    print("Positions:", positions)

    print("\n=== DRY RUN: BUY $10 of NVDA ===")
    sample = [{"action": "BUY", "symbol": "NVDA", "notional": 10, "rationale": "test"}]
    results = execute_trades(sample, account, positions, quotes)
    for r in results:
        print(f"  {r}")
