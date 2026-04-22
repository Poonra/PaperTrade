import os
import yaml
import asyncio
from dotenv import load_dotenv
from telegram import Bot
from telegram.constants import ParseMode

load_dotenv()

with open("config.yaml") as f:
    CONFIG = yaml.safe_load(f)


def _bot() -> Bot:
    token = os.getenv(CONFIG["api"]["telegram_token_env"])
    return Bot(token=token)


def _chat_id() -> str:
    return os.getenv(CONFIG["api"]["telegram_chat_id_env"])


async def _send(text: str) -> None:
    async with _bot() as bot:
        await bot.send_message(
            chat_id=_chat_id(),
            text=text,
            parse_mode=ParseMode.HTML,
        )


def send(text: str) -> None:
    """Synchronous wrapper — call this from non-async code."""
    asyncio.run(_send(text))


# ── Message formatters ─────────────────────────────────────────────────────────

def fmt_cycle_report(reasoning: str, trade_results: list[dict], account: dict) -> str:
    lines = ["<b>TRADING CYCLE</b>"]
    lines.append(f"Portfolio: <b>${account['portfolio_value']:,.2f}</b>  |  Cash: ${account['cash']:,.2f}")
    lines.append("")
    lines.append(f"<i>{reasoning}</i>")
    lines.append("")

    executed = [t for t in trade_results if t.get("status") == "executed"]
    rejected = [t for t in trade_results if t.get("status") == "rejected"]
    holds    = [t for t in trade_results if t.get("status") == "skipped"]

    if executed:
        lines.append("<b>Trades executed:</b>")
        for t in executed:
            lines.append(f"  {t['side'].upper()} {t['qty']} {t['symbol']} — {t.get('rationale', '')}")

    if rejected:
        lines.append("<b>Rejected:</b>")
        for t in rejected:
            lines.append(f"  {t['action']} {t['symbol']} — {t.get('reason', '')}")

    if holds:
        syms = ", ".join(t["symbol"] for t in holds)
        lines.append(f"<b>Held:</b> {syms}")

    if not executed and not rejected and not holds:
        lines.append("No trades this cycle.")

    return "\n".join(lines)


def fmt_daily_summary(summary: dict, positions: list[dict]) -> str:
    port_ret = summary["portfolio_return_pct"]
    spy_ret  = summary["spy_return_pct"]
    alpha    = summary["alpha_pct"]

    ret_sign  = "+" if port_ret >= 0 else ""
    spy_sign  = "+" if spy_ret  >= 0 else "" if spy_ret is not None else ""
    alpha_sign = "+" if alpha   >= 0 else "" if alpha is not None else ""

    lines = ["<b>DAILY SUMMARY</b>"]
    lines.append(f"Portfolio value : <b>${summary['current_value']:,.2f}</b>")
    lines.append(f"Your return     : <b>{ret_sign}{port_ret:.2f}%</b>")

    if spy_ret is not None:
        lines.append(f"SPY return      : {spy_sign}{spy_ret:.2f}%")
    if alpha is not None:
        marker = "BEATING" if alpha > 0 else "LAGGING"
        lines.append(f"Alpha           : {alpha_sign}{alpha:.2f}%  ({marker} S&P 500)")

    lines.append(f"Days tracked    : {summary['days_tracked']}")
    lines.append(f"Total trades    : {summary['total_trades']}  (B:{summary['total_buys']} S:{summary['total_sells']})")

    if positions:
        lines.append("")
        lines.append("<b>Open positions:</b>")
        for p in positions:
            plpc = p["unrealized_plpc"] * 100
            sign = "+" if plpc >= 0 else ""
            lines.append(
                f"  {p['symbol']:6s} {p['qty']:.0f} shares  {sign}{plpc:.2f}%  ${p['market_value']:,.0f}"
            )

    return "\n".join(lines)


def fmt_stop_loss_alert(order: dict) -> str:
    return (
        f"<b>STOP LOSS TRIGGERED</b>\n"
        f"Sold {order['qty']} {order['symbol']} "
        f"at a {order['loss_pct']:.2f}% loss."
    )


def fmt_error(context: str, error: str) -> str:
    return f"<b>BOT ERROR</b>\n{context}\n<code>{error}</code>"


# ── Test ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    send("Bot is online and connected.")
    print("Test message sent — check your Telegram.")
