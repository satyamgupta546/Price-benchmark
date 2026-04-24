"""
SAM Alert System — Send alerts to Slack #pricing-alerts channel.

Usage:
    from alert import send_alert, AlertLevel
    send_alert(AlertLevel.ERROR, "Blinkit scrape failed", details="Timeout after 3 retries")
    send_alert(AlertLevel.SUCCESS, "SAM daily run complete", details="6 cities, 12000 rows")
"""
import json
import os
import urllib.request
from datetime import datetime
from enum import Enum


class AlertLevel(Enum):
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# Slack channel: #pricing-alerts
SLACK_CHANNEL_ID = "C0AA94ADVN3"

# SAM bot Slack token — direct API, no webhook needed
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")


def send_alert(level: AlertLevel, title: str, details: str = "", city: str = "", platform: str = ""):
    """Send alert to Slack + print to stdout (for Cloud Logging)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")

    # Emoji per level
    emoji = {
        AlertLevel.SUCCESS: "✅",
        AlertLevel.WARNING: "⚠️",
        AlertLevel.ERROR: "❌",
        AlertLevel.CRITICAL: "🚨",
    }.get(level, "📢")

    # Log to stdout (always — shows in Cloud Logging)
    log_line = f"[SAM-ALERT] [{level.value.upper()}] {title}"
    if details:
        log_line += f" | {details}"
    if city:
        log_line += f" | city={city}"
    if platform:
        log_line += f" | platform={platform}"
    print(log_line, flush=True)

    # Send to Slack via SAM bot
    _slack_post(f"{emoji} *SAM: {title}*\n_{timestamp}_"
                + (f"\nCity: {city} | Platform: {platform}" if city or platform else "")
                + (f"\n```{details[:2000]}```" if details else ""))


def send_daily_summary(cities_data: dict, total_rows: int, duration_seconds: float,
                       errors: list = None):
    """Send daily summary to #pricing-alerts after full run."""
    duration_min = duration_seconds / 60
    date_str = datetime.now().strftime("%d %b %Y")
    ok_cities = sum(1 for info in cities_data.values() if info.get("rows", 0) > 0)
    total_cities = len(cities_data)

    # Build per-city table
    city_lines = []
    for pin, info in cities_data.items():
        city = info.get("city", pin)
        b = info.get("blinkit_ok", 0)
        j = info.get("jiomart_ok", 0)
        d = info.get("dmart_ok", 0)
        total = info.get("rows", 0)
        b_str = f"{b:,}" if b else "—"
        j_str = f"{j:,}" if j else "—"
        d_str = f"{d:,}" if d else "—"
        city_lines.append(f"  {city:<14} {b_str:>7}  {j_str:>7}  {d_str:>7}  {total:>7,}")

    # Status emoji
    if not errors:
        status = f":white_check_mark: {ok_cities}/{total_cities} cities OK"
    else:
        status = f":warning: {ok_cities}/{total_cities} cities OK | {len(errors)} errors"

    # Build message
    msg = f"*:bar_chart: Price Benchmark Daily Report — {date_str}*\n\n"
    msg += f"```\n"
    msg += f"  {'City':<14} {'Blinkit':>7}  {'Jiomart':>7}  {'DMart':>7}  {'Total':>7}\n"
    msg += f"  {'─'*14} {'─'*7}  {'─'*7}  {'─'*7}  {'─'*7}\n"
    for line in city_lines:
        msg += f"{line}\n"
    msg += f"```\n\n"
    msg += f":stopwatch: Duration: {duration_min:.0f} min | {status} | Total: {total_rows:,} rows"

    if errors:
        msg += f"\n\n*Errors:*\n"
        for e in errors[:5]:
            msg += f"  :x: {e[:100]}\n"

    # Print to stdout (for Cloud Logging)
    print(f"[SAM-ALERT] Daily summary: {total_rows} rows, {duration_min:.0f} min, {len(errors or [])} errors", flush=True)

    # Send via SAM bot
    _slack_post(msg)


def _slack_post(text: str, channel: str = SLACK_CHANNEL_ID):
    """Send message to Slack using SAM bot token."""
    token = SLACK_BOT_TOKEN
    if not token:
        print("[SAM-ALERT] No SLACK_BOT_TOKEN set — skipping Slack", flush=True)
        return
    try:
        payload = json.dumps({"channel": channel, "text": text}).encode()
        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        if not result.get("ok"):
            print(f"[SAM-ALERT] Slack API error: {result.get('error')}", flush=True)
    except Exception as e:
        print(f"[SAM-ALERT] Slack send failed: {e}", flush=True)
