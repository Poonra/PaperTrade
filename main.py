import os
import time
import yaml
import schedule
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient

import data
import analyst
import trader
import tracker
import telegram_bot

load_dotenv()

with open("config.yaml") as f:
    CONFIG = yaml.safe_load(f)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

_daily_summary_sent = False


def _trading_client() -> TradingClient:
    return TradingClient(
        api_key=os.getenv(CONFIG["api"]["alpaca_key_env"]),
        secret_key=os.getenv(CONFIG["api"]["alpaca_secret_env"]),
        paper=True,
    )


def market_is_open() -> bool:
    try:
        clock = _trading_client().get_clock()
        return clock.is_open
    except Exception as e:
        log.warning(f"Could not fetch market clock: {e}")
        return False


# ── Core cycle ─────────────────────────────────────────────────────────────────

def trading_cycle() -> None:
    global _daily_summary_sent

    if not market_is_open():
        log.info("Market closed — skipping cycle.")
        _daily_summary_sent = False  # reset so summary fires next close
        return

    log.info("=== TRADING CYCLE START ===")

    try:
        # 1. Fetch market snapshot
        snapshot = data.get_market_snapshot()
        account = snapshot["account"]
        positions = snapshot["positions"]
        quotes = snapshot["quotes"]
        log.info(f"Portfolio: ${account['portfolio_value']:,.2f}  |  Positions: {len(positions)}")

        # 2. Check stop losses independently of Claude
        stop_orders = trader.check_stop_losses(account, positions, quotes)
        for order in stop_orders:
            telegram_bot.send(telegram_bot.fmt_stop_loss_alert(order))
            tracker.log_trades([{**order, "status": "executed", "rationale": "stop_loss"}], quotes)

        # 3. Ask Claude for trade recommendations
        log.info("Calling Claude for analysis...")
        recommendation = analyst.analyse(snapshot)
        log.info(f"Claude reasoning: {recommendation['reasoning'][:120]}...")
        log.info(f"Recommendations: {len(recommendation['trades'])} trade(s)")

        # 4. Execute trades through safety gate
        results = trader.execute_trades(
            recommendation["trades"], account, positions, quotes
        )

        # 5. Log executed trades
        tracker.log_trades(results, quotes)
        tracker.log_portfolio_snapshot(account)

        # 6. Send Telegram cycle report
        msg = telegram_bot.fmt_cycle_report(
            recommendation["reasoning"], results, account
        )
        telegram_bot.send(msg)
        log.info("Cycle report sent to Telegram.")

    except Exception as e:
        log.error(f"Cycle error: {e}", exc_info=True)
        try:
            telegram_bot.send(telegram_bot.fmt_error("Trading cycle failed", str(e)))
        except Exception:
            pass

    log.info("=== TRADING CYCLE END ===")


def daily_summary() -> None:
    global _daily_summary_sent

    if _daily_summary_sent:
        return

    if market_is_open():
        return  # wait until market closes

    log.info("Sending daily summary...")
    try:
        account = data.get_account()
        positions = data.get_positions()
        tracker.log_portfolio_snapshot(account)
        summary = tracker.get_performance_summary(account)
        msg = telegram_bot.fmt_daily_summary(summary, positions)
        telegram_bot.send(msg)
        _daily_summary_sent = True
        log.info("Daily summary sent.")
    except Exception as e:
        log.error(f"Daily summary error: {e}", exc_info=True)


# ── Scheduler setup ────────────────────────────────────────────────────────────

def main() -> None:
    interval = CONFIG["schedule"]["run_interval_minutes"]
    log.info(f"Bot starting — cycle every {interval} min.")
    telegram_bot.send("Trading bot started.")

    # Run once immediately, then on schedule
    trading_cycle()

    schedule.every(interval).minutes.do(trading_cycle)
    schedule.every().day.at(CONFIG["schedule"]["market_close"]).do(daily_summary)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
