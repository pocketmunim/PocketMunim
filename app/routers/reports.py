from fastapi import APIRouter, Depends
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from app.services.report_service import ReportService
from supabase import Client
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/reports", tags=["Dynamic Reporting & Telemetry"])

class GenerateReportRequest(BaseModel):
    user_id: str
    start_date: str
    end_date: str

@router.post("/analytics", dependencies=[Depends(verify_zero_trust_signature)])
async def get_analytics_report(payload: GenerateReportRequest, db: Client = Depends(get_db)):
    data = ReportService.generate_intelligence_report(
        db=db,
        user_id=payload.user_id,
        start_date=payload.start_date,
        end_date=payload.end_date
    )
    return {"status": "SUCCESS", "data": data}