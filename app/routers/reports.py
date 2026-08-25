from fastapi import APIRouter, Depends
from supabase import Client
from pydantic import BaseModel
from typing import Dict, Any

from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from app.services.report_service import ReportService

router = APIRouter(prefix="/api/v1/reports", tags=["Intelligence & Reports"])


class ReportAnalyticsRequest(BaseModel):
    user_id: str
    start_date: str
    end_date: str


@router.post("/analytics", dependencies=[Depends(verify_zero_trust_signature)])
async def get_analytics_report(payload: ReportAnalyticsRequest, db: Client = Depends(get_db)) -> Dict[str, Any]:
    # Pass execution to the existing analytical service
    report_data = ReportService.generate_intelligence_report(
        db=db,
        user_id=payload.user_id,
        start_date=payload.start_date,
        end_date=payload.end_date
    )

    return {
        "success": True,
        "data": report_data
    }