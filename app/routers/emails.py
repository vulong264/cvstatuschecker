"""
REST endpoints for email templates and sending outreach emails.

Email Templates:
  GET    /api/emails/templates              — list templates
  POST   /api/emails/templates              — create template
  GET    /api/emails/templates/{id}         — get template
  PUT    /api/emails/templates/{id}         — update template
  DELETE /api/emails/templates/{id}         — delete template

Campaigns (sending):
  POST   /api/emails/send/{candidate_id}    — send outreach to one candidate
  POST   /api/emails/send-bulk             — send to multiple candidates
  GET    /api/emails/campaigns             — list sent campaigns
  GET    /api/emails/campaigns/{id}        — get campaign details
"""
from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Candidate, EmailTemplate, EmailCampaign
from app.services import candidate_service

router = APIRouter(prefix="/api/emails", tags=["emails"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class TemplateIn(BaseModel):
    name: str
    subject: str
    body_html: str
    body_text: Optional[str] = None
    is_active: bool = True


class TemplateOut(BaseModel):
    id: str
    name: str
    subject: str
    body_html: str
    body_text: Optional[str]
    is_active: bool
    created_at: Optional[str]

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_safe(cls, obj: EmailTemplate) -> "TemplateOut":
        return cls(
            id=obj.id,
            name=obj.name,
            subject=obj.subject,
            body_html=obj.body_html,
            body_text=obj.body_text,
            is_active=obj.is_active,
            created_at=obj.created_at.isoformat() if obj.created_at else None,
        )


class SendRequest(BaseModel):
    template_id: str
    sender_name: str = ""
    role: str = ""
    company: str = ""


class BulkSendRequest(BaseModel):
    candidate_ids: list[str]
    template_id: str
    sender_name: str = ""
    role: str = ""
    company: str = ""


class BulkSendResult(BaseModel):
    sent: int
    failed: list[str]  # candidate IDs that failed


class CampaignOut(BaseModel):
    id: str
    candidate_id: str
    candidate_name: Optional[str]
    candidate_email: Optional[str]
    template_id: Optional[str]
    rendered_subject: Optional[str]
    sent_at: Optional[str]
    tracking_token: str
    open_count: int
    opened_at: Optional[str]
    replied_at: Optional[str]

    @classmethod
    def from_orm_safe(cls, obj: EmailCampaign) -> "CampaignOut":
        return cls(
            id=obj.id,
            candidate_id=obj.candidate_id,
            candidate_name=obj.candidate.full_name if obj.candidate else None,
            candidate_email=obj.candidate.email if obj.candidate else None,
            template_id=obj.template_id,
            rendered_subject=obj.rendered_subject,
            sent_at=obj.sent_at.isoformat() if obj.sent_at else None,
            tracking_token=obj.tracking_token,
            open_count=obj.open_count or 0,
            opened_at=obj.opened_at.isoformat() if obj.opened_at else None,
            replied_at=obj.replied_at.isoformat() if obj.replied_at else None,
        )


# ---------------------------------------------------------------------------
# Template routes
# ---------------------------------------------------------------------------

@router.get("/templates", response_model=list[TemplateOut])
def list_templates(db: Session = Depends(get_db)):
    templates = db.query(EmailTemplate).order_by(EmailTemplate.created_at.desc()).all()
    return [TemplateOut.from_orm_safe(t) for t in templates]


@router.post("/templates", response_model=TemplateOut, status_code=201)
def create_template(body: TemplateIn, db: Session = Depends(get_db)):
    template = EmailTemplate(**body.model_dump())
    db.add(template)
    db.commit()
    return TemplateOut.from_orm_safe(template)


@router.get("/templates/{template_id}", response_model=TemplateOut)
def get_template(template_id: str, db: Session = Depends(get_db)):
    t = db.query(EmailTemplate).filter_by(id=template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return TemplateOut.from_orm_safe(t)


@router.put("/templates/{template_id}", response_model=TemplateOut)
def update_template(template_id: str, body: TemplateIn, db: Session = Depends(get_db)):
    t = db.query(EmailTemplate).filter_by(id=template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    for field, value in body.model_dump().items():
        setattr(t, field, value)
    db.commit()
    return TemplateOut.from_orm_safe(t)


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: str, db: Session = Depends(get_db)):
    t = db.query(EmailTemplate).filter_by(id=template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(t)
    db.commit()


# ---------------------------------------------------------------------------
# Sending routes
# ---------------------------------------------------------------------------

@router.post("/send/{candidate_id}", response_model=CampaignOut, status_code=201)
def send_to_candidate(
    candidate_id: str,
    body: SendRequest,
    db: Session = Depends(get_db),
):
    candidate = db.query(Candidate).filter_by(id=candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if not candidate.email:
        raise HTTPException(status_code=400, detail="Candidate has no email address")

    template = db.query(EmailTemplate).filter_by(id=body.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    campaign = candidate_service.send_outreach(
        db,
        candidate=candidate,
        template=template,
        sender_name=body.sender_name,
        role=body.role,
        company=body.company,
    )
    return CampaignOut.from_orm_safe(campaign)


@router.post("/send-bulk", response_model=BulkSendResult)
def send_bulk(body: BulkSendRequest, db: Session = Depends(get_db)):
    template = db.query(EmailTemplate).filter_by(id=body.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    sent = 0
    failed = []
    for cid in body.candidate_ids:
        candidate = db.query(Candidate).filter_by(id=cid).first()
        if not candidate or not candidate.email:
            failed.append(cid)
            continue
        try:
            candidate_service.send_outreach(
                db,
                candidate=candidate,
                template=template,
                sender_name=body.sender_name,
                role=body.role,
                company=body.company,
            )
            sent += 1
        except Exception:
            failed.append(cid)

    return BulkSendResult(sent=sent, failed=failed)


# ---------------------------------------------------------------------------
# Campaign listing
# ---------------------------------------------------------------------------

@router.get("/campaigns", response_model=list[CampaignOut])
def list_campaigns(
    candidate_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(EmailCampaign)
    if candidate_id:
        q = q.filter(EmailCampaign.candidate_id == candidate_id)
    campaigns = q.order_by(EmailCampaign.created_at.desc()).offset(offset).limit(limit).all()
    return [CampaignOut.from_orm_safe(c) for c in campaigns]


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: str, db: Session = Depends(get_db)):
    c = db.query(EmailCampaign).filter_by(id=campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return CampaignOut.from_orm_safe(c)
