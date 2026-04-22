import os
import json
import yaml
from dotenv import load_dotenv
import anthropic

load_dotenv()

with open("config.yaml") as f:
    CONFIG = yaml.safe_load(f)

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv(CONFIG["api"]["anthropic_key_env"]))
    return _client


# ── Prompt builders ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a disciplined quantitative stock trader managing a paper trading portfolio. \
Your goal is to outperform the S&P 500 (SPY) over time. You make decisions based on \
recent price action, momentum, and risk management — not speculation or hype.

You must always respond with valid JSON in exactly this structure:
{
  "reasoning": "<2-4 sentence summary of your overall market read>",
  "trades": [
    {
      "action": "BUY" | "SELL" | "HOLD",
      "symbol": "<ticker>",
      "notional": <dollar amount as a number, required for BUY only>,
      "rationale": "<one sentence>"
    }
  ]
}

Rules you must never break:
- Only trade symbols from the watchlist provided
- Never recommend more trades than the max_trades_per_run limit
- Do not recommend BUY if notional exceeds available buying power
- SELL closes the entire position — do not include notional for SELL
- Use fractional dollar amounts freely — no need to worry about share price
- If nothing looks attractive, return an empty trades list with your reasoning
"""


def _format_bars(bars: list[dict]) -> str:
    if not bars:
        return "  No recent data"
    lines = []
    for b in bars:
        chg = ""
        if len(lines) > 0:
            pass
        lines.append(f"  {b['date']}  O:{b['open']:.2f} H:{b['high']:.2f} L:{b['low']:.2f} C:{b['close']:.2f} V:{b['volume']:,}")
    return "\n".join(lines)


def _build_user_prompt(snapshot: dict) -> str:
    acct = snapshot["account"]
    positions = snapshot["positions"]
    quotes = snapshot["quotes"]
    bars = snapshot["bars"]
    risk = CONFIG["risk"]

    lines = []

    # Account
    lines.append("=== ACCOUNT ===")
    lines.append(f"Portfolio value : ${acct['portfolio_value']:,.2f}")
    lines.append(f"Cash            : ${acct['cash']:,.2f}")
    lines.append(f"Buying power    : ${acct['buying_power']:,.2f}")
    lines.append("")

    # Risk constraints
    lines.append("=== RISK CONSTRAINTS ===")
    lines.append(f"Max position    : {risk['max_position_pct']*100:.0f}% of portfolio  (${acct['portfolio_value'] * risk['max_position_pct']:,.0f})")
    lines.append(f"Max deployed    : {risk['max_portfolio_risk_pct']*100:.0f}% of portfolio")
    lines.append(f"Max trades/run  : {risk['max_trades_per_run']}")
    lines.append(f"Stop loss       : {risk['stop_loss_pct']*100:.0f}% from entry")
    lines.append(f"Min trade value : ${risk['min_trade_value']}")
    lines.append("")

    # Open positions
    lines.append("=== OPEN POSITIONS ===")
    if positions:
        for p in positions:
            plpc = p["unrealized_plpc"] * 100
            lines.append(
                f"  {p['symbol']:6s}  qty:{p['qty']:.0f}  entry:${p['avg_entry_price']:.2f}"
                f"  now:${p['current_price']:.2f}  P&L:{plpc:+.2f}%  value:${p['market_value']:,.0f}"
            )
    else:
        lines.append("  None")
    lines.append("")

    # Watchlist prices + bars
    lines.append("=== WATCHLIST: PRICE & RECENT BARS (IEX, daily OHLCV) ===")
    for sym in snapshot["watchlist"]:
        q = quotes.get(sym, {})
        mid = q.get("mid", 0)
        lines.append(f"\n{sym}  latest mid: ${mid:.2f}")
        lines.append(_format_bars(bars.get(sym, [])))

    lines.append(f"\nTimestamp: {snapshot['timestamp']}")
    lines.append("\nBased on the above, provide your trade recommendations as JSON.")

    return "\n".join(lines)


# ── Main entry point ───────────────────────────────────────────────────────────

def analyse(snapshot: dict) -> dict:
    """
    Call Claude with the market snapshot and return parsed trade recommendations.

    Returns:
        {
            "reasoning": str,
            "trades": [{"action", "symbol", "qty", "rationale"}, ...]
        }
    """
    client = _get_client()
    user_prompt = _build_user_prompt(snapshot)

    response = client.messages.create(
        model=CONFIG["claude"]["model"],
        max_tokens=CONFIG["claude"]["max_tokens"],
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # cache system prompt across runs
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if Claude wraps the JSON
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    result = json.loads(raw)

    # Normalise — ensure trades list always exists
    result.setdefault("reasoning", "")
    result.setdefault("trades", [])

    return result


if __name__ == "__main__":
    from data import get_market_snapshot
    snapshot = get_market_snapshot()
    result = analyse(snapshot)
    print("\n=== CLAUDE'S REASONING ===")
    print(result["reasoning"])
    print("\n=== TRADE RECOMMENDATIONS ===")
    for t in result["trades"]:
        qty = t.get("qty", "")
        print(f"  {t['action']:4s} {t['symbol']:6s} {qty}  — {t['rationale']}")
    if not result["trades"]:
        print("  No trades recommended this cycle.")
