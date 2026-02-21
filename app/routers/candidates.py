"""
REST endpoints for candidates.

GET  /api/candidates          — list / search candidates
GET  /api/candidates/{id}     — get one candidate
PATCH /api/candidates/{id}    — update status or notes
POST /api/candidates/sync     — trigger Google Drive scan
DELETE /api/candidates/{id}   — remove candidate
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models import Candidate
from app.services import candidate_service

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CandidateOut(BaseModel):
    id: str
    full_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    linkedin_url: Optional[str]
    location: Optional[str]
    status: str
    years_of_experience: Optional[float]
    current_title: Optional[str]
    current_company: Optional[str]
    main_skills: Optional[list]
    tech_stack: Optional[list]
    business_domains: Optional[list]
    education: Optional[list]
    work_history: Optional[list]
    cv_summary: Optional[str]
    drive_file_name: Optional[str]
    created_at: Optional[str]

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_safe(cls, obj: Candidate) -> "CandidateOut":
        return cls(
            id=obj.id,
            full_name=obj.full_name,
            email=obj.email,
            phone=obj.phone,
            linkedin_url=obj.linkedin_url,
            location=obj.location,
            status=obj.status,
            years_of_experience=obj.years_of_experience,
            current_title=obj.current_title,
            current_company=obj.current_company,
            main_skills=obj.main_skills or [],
            tech_stack=obj.tech_stack or [],
            business_domains=obj.business_domains or [],
            education=obj.education or [],
            work_history=obj.work_history or [],
            cv_summary=obj.cv_summary,
            drive_file_name=obj.drive_file_name,
            created_at=obj.created_at.isoformat() if obj.created_at else None,
        )


class StatusUpdate(BaseModel):
    status: str  # PENDING | EMAILED | EMAIL_OPENED | REPLIED | INTERESTED | NOT_INTERESTED


class SyncResponse(BaseModel):
    new: int
    updated: int
    skipped: int
    errors: int


VALID_STATUSES = {
    "PENDING", "EMAILED", "EMAIL_OPENED", "REPLIED", "INTERESTED", "NOT_INTERESTED"
}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[CandidateOut])
def list_candidates(
    status: Optional[str] = Query(None, description="Filter by status"),
    skill: Optional[str] = Query(None, description="Filter by skill (partial match in main_skills)"),
    domain: Optional[str] = Query(None, description="Filter by business domain"),
    min_years: Optional[float] = Query(None, description="Minimum years of experience"),
    max_years: Optional[float] = Query(None, description="Maximum years of experience"),
    q: Optional[str] = Query(None, description="Full-text search on name, title, summary"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    candidates = candidate_service.search_candidates(
        db,
        status=status,
        skill=skill,
        domain=domain,
        min_years=min_years,
        max_years=max_years,
        query=q,
        limit=limit,
        offset=offset,
    )
    return [CandidateOut.from_orm_safe(c) for c in candidates]


@router.get("/{candidate_id}", response_model=CandidateOut)
def get_candidate(candidate_id: str, db: Session = Depends(get_db)):
    c = db.query(Candidate).filter_by(id=candidate_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return CandidateOut.from_orm_safe(c)


@router.patch("/{candidate_id}", response_model=CandidateOut)
def update_candidate_status(
    candidate_id: str,
    body: StatusUpdate,
    db: Session = Depends(get_db),
):
    if body.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )
    c = db.query(Candidate).filter_by(id=candidate_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    c.status = body.status
    db.commit()
    return CandidateOut.from_orm_safe(c)


@router.delete("/{candidate_id}", status_code=204)
def delete_candidate(candidate_id: str, db: Session = Depends(get_db)):
    c = db.query(Candidate).filter_by(id=candidate_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    db.delete(c)
    db.commit()


@router.post("/sync", response_model=SyncResponse)
def sync_candidates(
    background_tasks: BackgroundTasks,
    folder_id: Optional[str] = Query(None, description="Override Drive folder ID"),
    force_reparse: bool = Query(False, description="Re-parse files already in the DB"),
    db: Session = Depends(get_db),
):
    """
    Trigger a sync of the Google Drive folder. Runs in the background.
    Returns immediately with a 200; the actual sync progresses asynchronously.

    For small folders you can also call this synchronously — just wait for it.
    """
    # For simplicity, run synchronously here (for large folders consider a task queue)
    result = candidate_service.sync_drive_folder(
        db, folder_id=folder_id, force_reparse=force_reparse
    )
    return SyncResponse(**result)
