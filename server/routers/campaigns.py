from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import ConfigValidationError
from server.core.scheduler import campaign_mgr

router = APIRouter()

class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    niche: str = Field(min_length=1, max_length=500)
    preset: str = Field(min_length=1, max_length=80)
    frequency_hours: float = Field(gt=0, le=8760)

@router.get("/")
def get_campaigns():
    return {"campaigns": campaign_mgr.get_campaigns()}

@router.post("/")
def create_campaign(req: CampaignCreate):
    try:
        c = campaign_mgr.add_campaign(req.name, req.niche, req.preset, req.frequency_hours)
        return {"message": "Campaign created", "campaign": c}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.post("/{cid}/toggle")
def toggle_campaign(cid: str):
    try:
        c = campaign_mgr.toggle(cid)
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {"message": "Toggled", "campaign": c}

@router.delete("/{cid}")
def delete_campaign(cid: str):
    if not campaign_mgr.delete(cid):
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {"message": "Deleted"}
