"""
High-level candidate operations:
  - Sync CVs from Google Drive (full scan or incremental)
  - Retrieve / filter candidates
  - Send outreach emails and record campaigns
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Candidate, EmailCampaign, EmailTemplate, EmailEvent
from app.services import drive_service, cv_parser, email_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CV ingestion
# ---------------------------------------------------------------------------

def sync_drive_folder(db: Session, folder_id: str | None = None, force_reparse: bool = False) -> dict:
    """
    Scan the configured Google Drive folder and upsert candidates.

    Returns a summary dict: {"new": N, "updated": N, "skipped": N, "errors": N}
    """
    summary = {"new": 0, "updated": 0, "skipped": 0, "errors": 0}

    for file_meta, content, ext in drive_service.iter_cv_files(folder_id):
        file_id = file_meta["id"]
        file_name = file_meta["name"]

        existing: Optional[Candidate] = (
            db.query(Candidate).filter_by(drive_file_id=file_id).first()
        )

        if existing and not force_reparse:
            summary["skipped"] += 1
            logger.debug("Skipping already-parsed file: %s", file_name)
            continue

        try:
            data = cv_parser.process_cv(content, ext)
        except Exception as exc:
            logger.error("Error parsing CV %s: %s", file_name, exc)
            summary["errors"] += 1
            continue

        if existing:
            _update_candidate(existing, data, file_meta)
            db.commit()
            summary["updated"] += 1
            logger.info("Updated candidate from: %s", file_name)
        else:
            candidate = _create_candidate(data, file_meta)
            db.add(candidate)
            db.commit()
            summary["new"] += 1
            logger.info("Created candidate from: %s | email=%s", file_name, data.email)

    return summary


def _create_candidate(data: cv_parser.CandidateData, file_meta: dict) -> Candidate:
    return Candidate(
        drive_file_id=file_meta["id"],
        drive_file_name=file_meta["name"],
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
        linkedin_url=data.linkedin_url,
        location=data.location,
        years_of_experience=data.years_of_experience,
        current_title=data.current_title,
        current_company=data.current_company,
        main_skills=data.main_skills,
        tech_stack=data.tech_stack,
        business_domains=data.business_domains,
        education=data.education,
        work_history=data.work_history,
        cv_summary=data.cv_summary,
        raw_cv_text=data.raw_cv_text,
        status="PENDING",
    )


def _update_candidate(candidate: Candidate, data: cv_parser.CandidateData, file_meta: dict):
    candidate.drive_file_name = file_meta["name"]
    candidate.full_name = data.full_name
    candidate.email = data.email
    candidate.phone = data.phone
    candidate.linkedin_url = data.linkedin_url
    candidate.location = data.location
    candidate.years_of_experience = data.years_of_experience
    candidate.current_title = data.current_title
    candidate.current_company = data.current_company
    candidate.main_skills = data.main_skills
    candidate.tech_stack = data.tech_stack
    candidate.business_domains = data.business_domains
    candidate.education = data.education
    candidate.work_history = data.work_history
    candidate.cv_summary = data.cv_summary
    candidate.raw_cv_text = data.raw_cv_text


# ---------------------------------------------------------------------------
# Searching / filtering
# ---------------------------------------------------------------------------

def search_candidates(
    db: Session,
    *,
    status: Optional[str] = None,
    skill: Optional[str] = None,
    domain: Optional[str] = None,
    min_years: Optional[float] = None,
    max_years: Optional[float] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Candidate]:
    q = db.query(Candidate)

    if status:
        q = q.filter(Candidate.status == status)
    if min_years is not None:
        q = q.filter(Candidate.years_of_experience >= min_years)
    if max_years is not None:
        q = q.filter(Candidate.years_of_experience <= max_years)
    if skill:
        # JSON contains search (SQLite compatible)
        q = q.filter(Candidate.main_skills.contains(skill))
    if domain:
        q = q.filter(Candidate.business_domains.contains(domain))
    if query:
        like = f"%{query}%"
        q = q.filter(
            Candidate.full_name.ilike(like)
            | Candidate.cv_summary.ilike(like)
            | Candidate.current_title.ilike(like)
        )

    return q.order_by(Candidate.created_at.desc()).offset(offset).limit(limit).all()


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def send_outreach(
    db: Session,
    candidate: Candidate,
    template: EmailTemplate,
    sender_name: str = "",
    role: str = "",
    company: str = "",
) -> EmailCampaign:
    """
    Render the template for the candidate, send via SendGrid, and persist an
    EmailCampaign record. Updates candidate.status to EMAILED.
    """
    if not candidate.email:
        raise ValueError(f"Candidate {candidate.id} has no email address.")

    variables = email_service.build_template_variables(
        candidate,
        sender_name=sender_name,
        role=role,
        company=company,
    )

    rendered_subject = email_service.render_template(template.subject, variables)
    rendered_html = email_service.render_template(template.body_html, variables)
    rendered_text = email_service.render_template(template.body_text or "", variables)

    # Create campaign record first so we have the tracking token
    campaign = EmailCampaign(
        candidate_id=candidate.id,
        template_id=template.id,
        rendered_subject=rendered_subject,
        rendered_body_html=rendered_html,
    )
    db.add(campaign)
    db.flush()  # get campaign.id + campaign.tracking_token

    # Send
    message_id = email_service.send_outreach_email(
        to_email=candidate.email,
        to_name=candidate.full_name or candidate.email,
        subject=rendered_subject,
        body_html=rendered_html,
        body_text=rendered_text,
        tracking_token=campaign.tracking_token,
        campaign_id=campaign.id,
    )

    campaign.sendgrid_message_id = message_id
    campaign.sent_at = datetime.now(timezone.utc)

    candidate.status = "EMAILED"
    db.commit()
    return campaign


# ---------------------------------------------------------------------------
# Event recording (called from tracking webhook routes)
# ---------------------------------------------------------------------------

def record_email_open(db: Session, campaign: EmailCampaign, ip: str = "", ua: str = ""):
    """Record an email open event and update statuses."""
    now = datetime.now(timezone.utc)

    event = EmailEvent(
        campaign_id=campaign.id,
        event_type="open",
        ip_address=ip,
        user_agent=ua,
    )
    db.add(event)

    campaign.open_count = (campaign.open_count or 0) + 1
    if not campaign.opened_at:
        campaign.opened_at = now

    candidate = campaign.candidate
    if candidate.status == "EMAILED":
        candidate.status = "EMAIL_OPENED"

    db.commit()


def record_email_reply(db: Session, campaign: EmailCampaign, raw_payload: dict = None):
    """Record a reply event and update candidate status."""
    now = datetime.now(timezone.utc)

    event = EmailEvent(
        campaign_id=campaign.id,
        event_type="reply",
        raw_payload=raw_payload or {},
    )
    db.add(event)

    if not campaign.replied_at:
        campaign.replied_at = now

    candidate = campaign.candidate
    if candidate.status in ("EMAILED", "EMAIL_OPENED"):
        candidate.status = "REPLIED"

    db.commit()


def record_sendgrid_event(db: Session, payload: dict):
    """
    Process a single SendGrid event webhook payload.
    https://docs.sendgrid.com/for-developers/tracking-events/event
    """
    token = payload.get("tracking_token") or payload.get("campaign_id")
    if not token:
        return

    # Try to find campaign by tracking_token OR sendgrid message id
    campaign = (
        db.query(EmailCampaign)
        .filter(
            (EmailCampaign.tracking_token == token)
            | (EmailCampaign.sendgrid_message_id == payload.get("sg_message_id"))
        )
        .first()
    )
    if not campaign:
        logger.warning("No campaign found for SendGrid event: %s", payload)
        return

    event_type = payload.get("event", "").lower()
    candidate = campaign.candidate

    event = EmailEvent(
        campaign_id=campaign.id,
        event_type=event_type,
        ip_address=payload.get("ip"),
        user_agent=payload.get("useragent"),
        url_clicked=payload.get("url"),
        raw_payload=payload,
    )
    db.add(event)

    now = datetime.now(timezone.utc)
    if event_type == "open":
        campaign.open_count = (campaign.open_count or 0) + 1
        if not campaign.opened_at:
            campaign.opened_at = now
        if candidate and candidate.status == "EMAILED":
            candidate.status = "EMAIL_OPENED"

    db.commit()
