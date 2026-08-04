from fastapi import APIRouter
from app.services.account_service import AccountService

router = APIRouter()

@router.post("/command/addaccount")
async def handle_addaccount(payload: str, user_id: str):
    service = AccountService(db_session=None, user_id=user_id)

    # If command is issued empty, return template
    if payload.strip() == "/addaccount":
        return {"text": service.get_copyable_template()}

    # Else, parse the text deterministically and pass to Pydantic schema
    # (Implementation deferred to execution layer)
    return {"text": "Account Registration Pipeline Triggered."}
