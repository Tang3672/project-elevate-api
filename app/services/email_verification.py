"""
Email Verification Service
===========================
Sends verification emails on signup.
Tokens stored in DB with 24hr expiry.
"""
import secrets
import logging
from datetime import datetime, timezone, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.core.config import settings
from app.db.user_repository import get_pool

logger = logging.getLogger(__name__)


async def create_verification_token(user_id: int) -> str:
    """Create a verification token and store in DB."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Ensure verification table exists
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS email_verifications (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                token       VARCHAR(100) NOT NULL UNIQUE,
                expires_at  TIMESTAMPTZ NOT NULL,
                used        BOOLEAN DEFAULT FALSE,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute(
            "DELETE FROM email_verifications WHERE user_id = $1",
            user_id
        )
        await conn.execute(
            "INSERT INTO email_verifications (user_id, token, expires_at) VALUES ($1, $2, $3)",
            user_id, token, expires
        )
    return token


async def verify_token(token: str) -> int | None:
    """Verify token and return user_id if valid."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT user_id, expires_at, used
               FROM email_verifications
               WHERE token = $1""",
            token
        )
        if not row:
            return None
        if row['used']:
            return None
        if row['expires_at'].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            return None
        # Mark as used
        await conn.execute(
            "UPDATE email_verifications SET used = TRUE WHERE token = $1",
            token
        )
        # Mark user as verified
        await conn.execute(
            "UPDATE users SET email_verified = TRUE WHERE id = $1",
            row['user_id']
        )
        return row['user_id']


async def send_verification_email(email: str, name: str, token: str, base_url: str):
    """Send verification email via SMTP."""
    verify_url = f"{base_url}/api/v1/auth/verify-email?token={token}"

    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:32px">
      <div style="background:#0a1628;padding:20px 24px;margin-bottom:24px">
        <span style="color:#fff;font-weight:700;font-size:16px">PE</span>
        <span style="color:#a0aec0;font-size:14px;margin-left:8px">Project Elevate</span>
      </div>
      <h2 style="color:#0a1628;margin-bottom:8px">Verify your email</h2>
      <p style="color:#4a5568;line-height:1.6">
        Hi {name or 'there'},<br><br>
        Click the button below to verify your email and activate your account.
        This link expires in 24 hours.
      </p>
      <a href="{verify_url}"
         style="display:inline-block;background:#1A4FD6;color:#fff;padding:12px 28px;
                text-decoration:none;font-weight:700;margin:20px 0">
        Verify Email →
      </a>
      <p style="color:#718096;font-size:12px;margin-top:24px">
        If you didn't create a Project Elevate account, ignore this email.
      </p>
    </div>
    """

    if not settings.SMTP_HOST or not settings.SMTP_USER:
        logger.warning(f"SMTP not configured — verification URL: {verify_url}")
        return

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Verify your Project Elevate account'
        msg['From']    = settings.EMAIL_FROM or f"Project Elevate <{settings.SMTP_USER}>"
        msg['To']      = email
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT or 465) as server:
            server.login(settings.SMTP_USER, settings.SMTP_PASS)
            server.sendmail(settings.SMTP_USER, email, msg.as_string())
        logger.info(f"Verification email sent to {email}")
    except Exception as e:
        logger.error(f"Failed to send verification email: {e}")
        # Don't block registration if email fails
