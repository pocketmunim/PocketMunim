import base64
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from app.schemas.user import UserProfileUpdate, AvatarUploadRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/users", tags=["User Profile"])


@router.post("/profile/update", dependencies=[Depends(verify_zero_trust_signature)])
async def update_profile(payload: UserProfileUpdate, db: Client = Depends(get_db)):
    try:
        res = db.table('users').update({
            "full_name": payload.full_name,
            "currency": payload.currency
        }).eq('user_id', payload.user_id).execute()

        return {"success": True, "message": "Profile updated successfully."}
    except Exception as e:
        logger.error(f"Profile update failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to update profile.")


@router.post("/profile/avatar", dependencies=[Depends(verify_zero_trust_signature)])
async def upload_avatar(payload: AvatarUploadRequest, db: Client = Depends(get_db)):
    try:
        file_bytes = base64.b64decode(payload.base64_data)
        file_path = f"{payload.user_id}/avatar_{payload.file_name}"

        # Upload to Supabase Storage with upsert to overwrite old avatar
        db.storage.from_('avatars').upload(
            file_path,
            file_bytes,
            file_options={"content-type": payload.content_type, "upsert": "true"}
        )

        # Get public URL
        public_url = db.storage.from_('avatars').get_public_url(file_path)

        # Update users table
        db.table('users').update({"avatar_url": public_url}).eq('user_id', payload.user_id).execute()

        return {"success": True, "message": "Avatar uploaded", "avatar_url": public_url}
    except Exception as e:
        logger.error(f"Avatar upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Avatar upload failed: {str(e)}")