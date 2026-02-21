"""
Tracking endpoints — receive open/reply signals and update campaign status.

Open tracking (custom pixel):
  GET /api/track/open/{token}.gif
    — Called when the email client loads the embedded tracking pixel.
    — Returns a 1×1 transparent GIF.
    — Records IP + User-Agent + timestamp.

SendGrid Event Webhook:
  POST /api/track/sendgrid
    — SendGrid posts an array of event objects here.
    — Configure in SendGrid → Settings → Mail Settings → Event Webhook.
    — Events: delivered, open, click, bounce, unsubscribed, ...

SendGrid Inbound Parse (reply detection):
  POST /api/track/reply
    — SendGrid posts inbound email data here when a candidate replies.
    — Configure in SendGrid → Settings → Inbound Parse.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import EmailCampaign
from app.services import candidate_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/track", tags=["tracking"])

# 1×1 transparent GIF bytes
_TRANSPARENT_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
    b"!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
    b"\x00\x00\x02\x02D\x01\x00;"
)


# ---------------------------------------------------------------------------
# Custom tracking pixel
# ---------------------------------------------------------------------------

@router.get("/open/{token}.gif")
async def track_open(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Record email open when the tracking pixel is loaded.
    Always returns a 1×1 transparent GIF so mail clients don't show an error.
    """
    campaign = db.query(EmailCampaign).filter_by(tracking_token=token).first()
    if campaign:
        ip = request.client.host if request.client else ""
        ua = request.headers.get("user-agent", "")
        candidate_service.record_email_open(db, campaign, ip=ip, ua=ua)
        logger.info(
            "Email opened | campaign=%s candidate=%s ip=%s",
            campaign.id,
            campaign.candidate_id,
            ip,
        )
    else:
        logger.warning("Unknown tracking token: %s", token)

    return Response(
        content=_TRANSPARENT_GIF,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


# ---------------------------------------------------------------------------
# SendGrid Event Webhook
# ---------------------------------------------------------------------------

@router.post("/sendgrid")
async def sendgrid_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Receive SendGrid event webhook payloads.

    Setup in SendGrid:
      Settings → Mail Settings → Event Webhook → HTTP POST URL:
      https://your-app.example.com/api/track/sendgrid

    Recommended events to enable:
      - Delivered, Opens, Clicks, Bounces, Unsubscribes
    """
    try:
        events = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(events, list):
        events = [events]

    processed = 0
    for event in events:
        try:
            candidate_service.record_sendgrid_event(db, event)
            processed += 1
        except Exception as exc:
            logger.error("Error processing SendGrid event %s: %s", event, exc)

    return {"processed": processed}


# ---------------------------------------------------------------------------
# SendGrid Inbound Parse — reply detection
# ---------------------------------------------------------------------------

@router.post("/reply")
async def inbound_reply(request: Request, db: Session = Depends(get_db)):
    """
    Detect replies via SendGrid Inbound Parse.

    Setup in SendGrid:
      Settings → Inbound Parse → Add Host & URL:
      URL: https://your-app.example.com/api/track/reply

    SendGrid parses the inbound email and posts form data including:
      - 'from': sender address (the candidate's reply-from)
      - 'to': recipient (your tracking address)
      - 'subject': reply subject
      - 'text': plain-text body

    Strategy: match the candidate's email address to find their most recent
    campaign and record the reply.
    """
    form = await request.form()
    from_email = form.get("from", "")
    # SendGrid wraps "Name <email>" — extract just the address
    import re
    match = re.search(r"[\w.+\-]+@[\w\-]+\.[\w.]+", from_email)
    email_addr = match.group(0) if match else from_email

    if not email_addr:
        return {"detail": "no sender email found"}

    # Find the most recent campaign for this email
    from app.models import Candidate
    candidate = db.query(Candidate).filter(Candidate.email.ilike(email_addr)).first()
    if not candidate:
        logger.warning("Inbound reply from unknown email: %s", email_addr)
        return {"detail": "candidate not found"}

    campaign = (
        db.query(EmailCampaign)
        .filter_by(candidate_id=candidate.id)
        .order_by(EmailCampaign.sent_at.desc())
        .first()
    )
    if not campaign:
        return {"detail": "no campaign found"}

    raw_payload = {
        "from": from_email,
        "to": form.get("to"),
        "subject": form.get("subject"),
        "text": form.get("text", "")[:2000],  # truncate body
    }
    candidate_service.record_email_reply(db, campaign, raw_payload=raw_payload)
    logger.info(
        "Reply recorded | candidate=%s campaign=%s",
        candidate.id,
        campaign.id,
    )
    return {"detail": "reply recorded"}
