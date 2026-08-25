from pydantic import BaseModel, Field

class UserProfileUpdate(BaseModel):
    user_id: str
    full_name: str = Field(..., min_length=2, max_length=150)
    currency: str = "INR"

class AvatarUploadRequest(BaseModel):
    user_id: str
    file_name: str
    content_type: str
    base64_data: str