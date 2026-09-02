import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from app.api import deps
from app.db.models import User
from app.services.file_service import create_presigned_upload, get_file_info
from app.core.rate_limit import limiter

router = APIRouter()
logger = logging.getLogger(__name__)


class PresignRequest(BaseModel):
    file_name: str
    mime_type: str = "application/octet-stream"
    expires_in: int = 3600


class PresignResponse(BaseModel):
    file_id: str
    upload_url: str
    method: str
    expires_in: int


@router.post("/presign", response_model=PresignResponse)
@limiter.limit("20/minute")
async def presign_upload(
    request: Request,
    body: PresignRequest,
    current_user: User = Depends(deps.get_current_user),
):
    if len(body.file_name) > 255:
        raise HTTPException(status_code=422, detail="file_name too long")
    if body.expires_in < 60 or body.expires_in > 86400:
        raise HTTPException(status_code=422, detail="expires_in must be 60-86400")
    info = create_presigned_upload(body.file_name, body.mime_type, body.expires_in)
    return PresignResponse(
        file_id=info["file_id"],
        upload_url=info["upload_url"],
        method=info["method"],
        expires_in=info["expires_in"],
    )


@router.get("/{file_id}")
@limiter.limit("30/minute")
async def get_file(
    request: Request,
    file_id: str,
    current_user: User = Depends(deps.get_current_user),
):
    info = get_file_info(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="File not found or expired")
    return info
