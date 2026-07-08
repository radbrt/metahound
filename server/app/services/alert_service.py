"""
Email (aiosmtplib) and Slack (slack-sdk webhook) alert delivery.
"""
import asyncio
import logging

from app.config import settings
from app.models import Anomaly, Org

logger = logging.getLogger(__name__)


def _format_anomaly_text(anomalies: list[Anomaly]) -> str:
    lines = [f"Metahound detected {len(anomalies)} anomal{'y' if len(anomalies) == 1 else 'ies'}:\n"]
    for a in anomalies:
        ts_str = a.anomaly_ts.isoformat() if a.anomaly_ts else "unknown time"
        lines.append(
            f"  • {a.metric_uri}  |  value={a.observed_value}  |  z={a.z_score:.2f}  |  {ts_str}"
        )
    return "\n".join(lines)


async def _send_email(to: str, subject: str, body: str) -> None:
    import aiosmtplib
    from email.mime.text import MIMEText

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        start_tls=True,
    )


async def _send_slack(webhook_url: str, text: str) -> None:
    from slack_sdk.webhook.async_client import AsyncWebhookClient

    client = AsyncWebhookClient(webhook_url)
    response = await client.send(text=text)
    if response.status_code != 200:
        logger.warning("Slack webhook returned %s: %s", response.status_code, response.body)


async def send_alerts_async(org: Org, anomalies: list[Anomaly]) -> None:
    """Send email and/or Slack alerts for the given anomalies."""
    if not anomalies or not org.alerts_enabled:
        return

    text = _format_anomaly_text(anomalies)
    subject = f"[Metahound] {len(anomalies)} anomal{'y' if len(anomalies) == 1 else 'ies'} detected"

    tasks = []
    if org.alert_email and settings.smtp_host:
        tasks.append(_send_email(org.alert_email, subject, text))
    if org.slack_webhook_url:
        tasks.append(_send_slack(org.slack_webhook_url, text))

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("Alert delivery error: %s", result)


def send_alerts(org: Org, anomalies: list[Anomaly]) -> None:
    """Synchronous wrapper — safe to call from APScheduler background thread."""
    asyncio.run(send_alerts_async(org, anomalies))
