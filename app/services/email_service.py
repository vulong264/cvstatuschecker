"""
Email service — sends outreach emails via SendGrid with:

  1. Tracking pixel  — 1×1 GIF embedded in HTML (`/api/track/open/{token}.gif`)
  2. SendGrid event webhook — open, click, bounce, unsubscribe events
  3. Inbound Parse webhook — reply detection (`/api/track/reply`)

Variable substitution in templates uses {{variable}} syntax.
"""
import logging
import re
from datetime import datetime, timezone

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail, To, From, Subject,
    HtmlContent, PlainTextContent,
    CustomArg,
)

from app.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def render_template(template_str: str, variables: dict) -> str:
    """
    Replace {{variable_name}} placeholders in a template string.
    Unknown variables are left as-is.
    """
    def replacer(match):
        key = match.group(1).strip()
        return str(variables.get(key, match.group(0)))

    return re.sub(r"\{\{(\w+)\}\}", replacer, template_str)


def build_tracking_pixel_html(token: str, base_url: str) -> str:
    """Return an invisible 1×1 GIF img tag for open tracking."""
    url = f"{base_url}/api/track/open/{token}.gif"
    return f'<img src="{url}" width="1" height="1" alt="" style="display:none;" />'


# ---------------------------------------------------------------------------
# SendGrid sending
# ---------------------------------------------------------------------------

def send_outreach_email(
    *,
    to_email: str,
    to_name: str,
    subject: str,
    body_html: str,
    body_text: str,
    tracking_token: str,
    campaign_id: str,
) -> str | None:
    """
    Send an outreach email via SendGrid.

    Injects a tracking pixel into the HTML body.
    Attaches campaign_id and tracking_token as SendGrid custom args so
    the event webhook can identify which campaign each event belongs to.

    Returns the SendGrid X-Message-Id on success, or None on failure.
    """
    settings = get_settings()

    # Inject tracking pixel just before </body>
    pixel_html = build_tracking_pixel_html(tracking_token, settings.app_base_url)
    if "</body>" in body_html:
        body_html = body_html.replace("</body>", f"{pixel_html}</body>")
    else:
        body_html += pixel_html

    message = Mail(
        from_email=From(settings.sendgrid_from_email, settings.sendgrid_from_name),
        to_emails=To(to_email, to_name),
        subject=Subject(subject),
        html_content=HtmlContent(body_html),
        plain_text_content=PlainTextContent(body_text or _html_to_plain(body_html)),
    )

    # Custom args appear in SendGrid webhook events so we can identify the campaign
    message.custom_arg = [
        CustomArg("campaign_id", campaign_id),
        CustomArg("tracking_token", tracking_token),
    ]

    # SendGrid built-in tracking (open + click tracking)
    message.tracking_settings = _tracking_settings()

    # Set reply-to so replies land in SendGrid Inbound Parse
    # (configure the inbound parse webhook in your SendGrid dashboard)
    # message.reply_to = settings.sendgrid_reply_to_email  # optional

    try:
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        response = sg.send(message)
        message_id = response.headers.get("X-Message-Id")
        logger.info(
            "Email sent to %s | status=%s | message_id=%s",
            to_email,
            response.status_code,
            message_id,
        )
        return message_id
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_email, exc)
        raise


def _tracking_settings():
    """SendGrid tracking settings object (enables open + click tracking)."""
    from sendgrid.helpers.mail import TrackingSettings, OpenTracking, ClickTracking

    ts = TrackingSettings()
    ts.open_tracking = OpenTracking(enable=True)
    ts.click_tracking = ClickTracking(enable=True, enable_text=False)
    return ts


def _html_to_plain(html: str) -> str:
    """Very basic HTML → plain text for the plaintext fallback."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Template variables helper
# ---------------------------------------------------------------------------

def build_template_variables(candidate, sender_name: str = "", role: str = "", company: str = "") -> dict:
    """
    Build the variable dict used to render email templates for a given candidate.
    """
    return {
        "candidate_name": candidate.full_name or "there",
        "first_name": (candidate.full_name or "").split()[0] if candidate.full_name else "there",
        "sender_name": sender_name,
        "role": role,
        "company": company,
        "candidate_title": candidate.current_title or "",
        "candidate_company": candidate.current_company or "",
        "years_of_experience": str(int(candidate.years_of_experience or 0)),
        "top_skills": ", ".join((candidate.main_skills or [])[:5]),
    }
