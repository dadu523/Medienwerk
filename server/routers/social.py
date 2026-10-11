"""Truthful status endpoints for currently unsupported social integrations."""

from fastapi import APIRouter, HTTPException

router = APIRouter()

_NOT_IMPLEMENTED = "This social integration is not implemented. YouTube uploads use the registered-video publish endpoint and its OAuth flow."


@router.get("/status")
def get_social_status():
    # Legacy OAuthToken rows may contain demo values. They are not evidence of
    # a verified provider session, so no platform is reported as connected.
    return {"youtube": False, "tiktok": False, "instagram": False,
            "verified": {"youtube": False, "tiktok": False, "instagram": False}}


@router.get("/youtube/auth")
def youtube_auth_url():
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED)


@router.post("/youtube/callback")
def youtube_callback():
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED)


@router.post("/tiktok/auth")
def tiktok_auth_url():
    raise HTTPException(status_code=501, detail="TikTok authorization is not implemented")


@router.post("/instagram/auth")
def instagram_auth_url():
    raise HTTPException(status_code=501, detail="Instagram authorization is not implemented")


@router.post("/publish/youtube")
def publish_to_youtube():
    raise HTTPException(status_code=501, detail="Use /api/publish/youtube with a registered media ID")
