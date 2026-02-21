"""
SQLAlchemy ORM models for CV Status Checker.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Text, DateTime, Boolean,
    ForeignKey, Float, JSON
)
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


class Candidate(Base):
    """
    A candidate parsed from a CV file.
    Status flow:
      PENDING → EMAILED → EMAIL_OPENED → REPLIED → INTERESTED / NOT_INTERESTED
    """
    __tablename__ = "candidates"

    id = Column(String, primary_key=True, default=new_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Source
    drive_file_id = Column(String, unique=True, index=True)
    drive_file_name = Column(String)

    # Status
    # PENDING | EMAILED | EMAIL_OPENED | REPLIED | INTERESTED | NOT_INTERESTED
    status = Column(String, default="PENDING", index=True)

    # Identity
    full_name = Column(String)
    email = Column(String, index=True)
    phone = Column(String)
    linkedin_url = Column(String)
    location = Column(String)

    # Experience
    years_of_experience = Column(Float)           # e.g. 7.5
    current_title = Column(String)
    current_company = Column(String)

    # Skills stored as JSON arrays
    main_skills = Column(JSON)                    # ["Python", "FastAPI", ...]
    tech_stack = Column(JSON)                     # ["PostgreSQL", "Redis", ...]
    business_domains = Column(JSON)               # ["Fintech", "E-commerce", ...]

    # Education
    education = Column(JSON)                      # [{"degree": "...", "institution": "..."}]

    # Employment history (summary)
    work_history = Column(JSON)                   # [{"company": "...", "role": "...", "years": 2}]

    # Raw extracted text and Claude summary
    raw_cv_text = Column(Text)
    cv_summary = Column(Text)

    # Relationships
    email_campaigns = relationship("EmailCampaign", back_populates="candidate")


class EmailTemplate(Base):
    """
    Reusable email templates with variable substitution.
    Variables: {{candidate_name}}, {{sender_name}}, {{role}}, {{company}}
    """
    __tablename__ = "email_templates"

    id = Column(String, primary_key=True, default=new_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    name = Column(String, nullable=False)          # e.g. "Senior Engineer Outreach"
    subject = Column(String, nullable=False)
    body_html = Column(Text, nullable=False)       # HTML with {{variables}}
    body_text = Column(Text)                       # plain-text fallback
    is_active = Column(Boolean, default=True)

    campaigns = relationship("EmailCampaign", back_populates="template")


class EmailCampaign(Base):
    """
    A single outreach email sent to one candidate using a template.
    """
    __tablename__ = "email_campaigns"

    id = Column(String, primary_key=True, default=new_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    template_id = Column(String, ForeignKey("email_templates.id"))

    # The rendered subject/body actually sent
    rendered_subject = Column(String)
    rendered_body_html = Column(Text)

    # Delivery info
    sent_at = Column(DateTime(timezone=True))
    sendgrid_message_id = Column(String, index=True)

    # Tracking
    tracking_token = Column(String, unique=True, index=True, default=new_uuid)
    opened_at = Column(DateTime(timezone=True))
    open_count = Column(Integer, default=0)
    replied_at = Column(DateTime(timezone=True))

    candidate = relationship("Candidate", back_populates="email_campaigns")
    template = relationship("EmailTemplate", back_populates="campaigns")
    events = relationship("EmailEvent", back_populates="campaign")


class EmailEvent(Base):
    """
    Individual tracking events for an email campaign (open, click, reply, bounce, etc.).
    """
    __tablename__ = "email_events"

    id = Column(String, primary_key=True, default=new_uuid)
    occurred_at = Column(DateTime(timezone=True), default=utcnow)

    campaign_id = Column(String, ForeignKey("email_campaigns.id"), nullable=False)

    # open | click | reply | bounce | delivered | unsubscribed
    event_type = Column(String, nullable=False, index=True)

    # Optional metadata
    ip_address = Column(String)
    user_agent = Column(String)
    url_clicked = Column(String)        # for click events
    raw_payload = Column(JSON)          # full webhook payload

    campaign = relationship("EmailCampaign", back_populates="events")
