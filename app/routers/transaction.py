from fastapi import APIRouter, Depends
from supabase import Client
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from app.schemas.transaction import CreateTransactionRequest
from datetime import date

router = APIRouter(prefix="/api/v1/transactions", tags=["Transactions Ledger"])


@router.post("/create", dependencies=[Depends(verify_zero_trust_signature)])
async def create_transaction(payload: CreateTransactionRequest, db: Client = Depends(get_db)):
    rpc_payload = {
        "user_id": payload.user_id,
        "item_name": payload.item_name.strip(),
        "amount": payload.amount,
        "type": payload.type.value,
        "account_id": payload.account_id,
        "category": payload.category,
        "transaction_date": payload.transaction_date or str(date.today())
    }

    # Defers entirely to the locked, ACID-compliant database RPC
    res = db.rpc("log_transaction_atomic", {"payload": rpc_payload}).execute()

    return {"status": "SUCCESS", "data": res.data}