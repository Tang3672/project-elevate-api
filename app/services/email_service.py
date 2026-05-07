"""
Email Service
=============
Sends weekly alert digest emails to PIs.
Uses Python's built-in smtplib — no paid email service needed for early stage.

For production, swap SMTP for SendGrid/Resend by changing _send_email().
Configure in .env:
  EMAIL_HOST=smtp.gmail.com
  EMAIL_PORT=587
  EMAIL_USER=your@gmail.com
  EMAIL_PASSWORD=your_app_password   (Gmail App Password, not account password)
  EMAIL_FROM=Project Elevate <alerts@projectelevate.io>
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List
from datetime import datetime

from app.core.config import settings
from app.models.watchlist import Alert

logger = logging.getLogger(__name__)

ALERT_COLORS = {
    "high":   "#D72638",
    "medium": "#B45309",
    "low":    "#0369A1",
}

ALERT_ICONS = {
    "fda_recall":      "⚠",
    "fda_adverse":     "🔴",
    "clinical_trial":  "🧪",
    "disease_burden":  "📊",
    "hrsa_shortage":   "🏥",
    "funding":         "💰",
    "competitor":      "⚡",
}


def build_digest_email(
    user_name:  str,
    user_email: str,
    alerts:     List[Alert],
    week_of:    str,
) -> str:
    """Build HTML email body for the weekly digest."""
    if not alerts:
        return ""

    high_alerts   = [a for a in alerts if a.severity == "high"]
    medium_alerts = [a for a in alerts if a.severity == "medium"]
    low_alerts    = [a for a in alerts if a.severity == "low"]

    name_display = user_name or user_email.split("@")[0]

    rows_html = ""
    for alert in alerts[:20]:   # cap at 20 per email
        color = ALERT_COLORS.get(alert.severity, "#334767")
        icon  = ALERT_ICONS.get(alert.alert_type, "📌")
        link  = f'<a href="{alert.source_url}" style="color:#1A4FD6">View source →</a>' if alert.source_url else ""
        rows_html += f"""
        <tr>
          <td style="padding:12px 16px;border-bottom:1px solid #eef1f6;vertical-align:top">
            <div style="display:flex;align-items:flex-start;gap:10px">
              <span style="font-size:18px;flex-shrink:0">{icon}</span>
              <div>
                <div style="font-weight:600;color:#0f1929;font-size:13px;margin-bottom:4px">{alert.title}</div>
                <div style="color:#334767;font-size:12px;line-height:1.6;margin-bottom:6px">{alert.summary[:250]}</div>
                <div style="display:flex;gap:12px;align-items:center">
                  <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:{color};background:{color}15;padding:2px 8px;border-radius:2px">{alert.severity.upper()}</span>
                  <span style="font-size:10px;color:#7a92b0">{alert.created_at.strftime('%b %d, %Y')}</span>
                  {link}
                </div>
              </div>
            </div>
          </td>
        </tr>"""

    summary_line = f"{len(high_alerts)} high priority" if high_alerts else ""
    if medium_alerts:
        summary_line += f"{', ' if summary_line else ''}{len(medium_alerts)} medium"
    if low_alerts:
        summary_line += f"{', ' if summary_line else ''}{len(low_alerts)} low priority"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:32px 16px">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #dde2ec">

        <!-- Header -->
        <tr>
          <td style="background:#0A1628;padding:24px 32px">
            <div style="display:flex;align-items:center;gap:10px">
              <div style="background:#1A4FD6;width:32px;height:32px;display:inline-flex;align-items:center;justify-content:center;font-weight:700;color:#fff;font-size:12px;margin-right:10px">PE</div>
              <span style="color:#fff;font-size:18px;font-weight:700">Project Elevate</span>
              <span style="color:#5A7BBF;font-size:12px;margin-left:8px">Weekly Intelligence Digest</span>
            </div>
          </td>
        </tr>

        <!-- Summary bar -->
        <tr>
          <td style="background:#1A4FD6;padding:12px 32px">
            <span style="color:#fff;font-size:13px;font-weight:600">
              Week of {week_of} · {len(alerts)} new signal{'s' if len(alerts) != 1 else ''} · {summary_line}
            </span>
          </td>
        </tr>

        <!-- Greeting -->
        <tr>
          <td style="padding:24px 32px 12px">
            <p style="margin:0;color:#0f1929;font-size:14px;line-height:1.7">
              Hi {name_display},<br><br>
              Your Project Elevate surveillance system detected <strong>{len(alerts)} new signal{'s' if len(alerts) != 1 else ''}</strong>
              relevant to your watchlists this week. Here's your intelligence briefing:
            </p>
          </td>
        </tr>

        <!-- Alerts table -->
        <tr>
          <td style="padding:0 32px 24px">
            <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #dde2ec">
              {rows_html}
            </table>
          </td>
        </tr>

        <!-- CTA -->
        <tr>
          <td style="padding:0 32px 32px;text-align:center">
            <a href="https://preeminent-zuccutto-bd1f9d.netlify.app"
               style="display:inline-block;background:#1A4FD6;color:#fff;font-weight:700;font-size:13px;padding:12px 28px;text-decoration:none;letter-spacing:.02em">
              View Full Dashboard →
            </a>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f4f6f9;padding:16px 32px;border-top:1px solid #dde2ec">
            <p style="margin:0;color:#7a92b0;font-size:11px;line-height:1.6">
              You're receiving this because you have active watchlists on Project Elevate.
              Signals sourced from CDC, FDA, CMS, Census, ClinicalTrials.gov, and HRSA.
              <br>© 2026 Project Elevate · Weekly digest every Monday 8am ET
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""
    return html


async def send_digest_email(
    user_email: str,
    user_name:  str,
    alerts:     List[Alert],
) -> bool:
    """
    Send the weekly digest email.
    Returns True if sent successfully.
    """
    if not alerts:
        logger.info(f"No alerts for {user_email} — skipping digest")
        return False

    if not getattr(settings, 'EMAIL_HOST', None) or not getattr(settings, 'EMAIL_USER', None):
        logger.warning("Email not configured — skipping digest send. Add EMAIL_HOST/EMAIL_USER to .env")
        return False

    week_of = datetime.utcnow().strftime("%B %d, %Y")
    html    = build_digest_email(user_name, user_email, alerts, week_of)
    if not html:
        return False

    subject = f"Project Elevate: {len(alerts)} new signal{'s' if len(alerts) != 1 else ''} this week"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = getattr(settings, 'EMAIL_FROM', f"Project Elevate <{settings.EMAIL_USER}>")
        msg["To"]      = user_email

        # Plain text fallback
        plain = f"Project Elevate Weekly Digest\n\n{len(alerts)} new signals this week.\n\nView your dashboard: https://preeminent-zuccutto-bd1f9d.netlify.app"
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))

        port = int(getattr(settings, 'EMAIL_PORT', 587))
        with smtplib.SMTP(settings.EMAIL_HOST, port) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.EMAIL_USER, settings.EMAIL_PASSWORD)
            server.sendmail(settings.EMAIL_USER, user_email, msg.as_string())

        logger.info(f"Digest sent to {user_email}: {len(alerts)} alerts")
        return True

    except Exception as e:
        logger.error(f"Failed to send digest to {user_email}: {e}")
        return False


async def send_all_weekly_digests():
    """
    Send weekly digest emails to all users with new alerts.
    Called by the scheduler every Monday.
    """
    from app.db.user_repository import get_all_users
    from app.db.watchlist_repository import get_recent_alerts_for_digest

    try:
        users = await get_all_users()
    except Exception as e:
        logger.error(f"Failed to fetch users for digest: {e}")
        return

    sent = 0
    for user in users:
        try:
            alerts = await get_recent_alerts_for_digest(user['id'], days=7)
            if alerts:
                success = await send_digest_email(
                    user_email = user['email'],
                    user_name  = user.get('name', ''),
                    alerts     = alerts,
                )
                if success:
                    sent += 1
        except Exception as e:
            logger.error(f"Digest failed for user {user['id']}: {e}")

    logger.info(f"Weekly digests sent: {sent}/{len(users)} users")
