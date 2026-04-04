"""レポートAPI（/api/reports）- PHASE 4で完全実装"""
from fastapi import APIRouter

router = APIRouter()


@router.post("/reports/scout")
def generate_scout_report(body: dict):
    """スカウティングレポートPDF生成（TASK-040以降で実装）"""
    return {"success": True, "data": {"message": "レポート生成機能は今後実装予定"}}


@router.post("/reports/growth")
def generate_growth_report(body: dict):
    """選手成長レポートPDF生成（TASK-040以降で実装）"""
    return {"success": True, "data": {"message": "レポート生成機能は今後実装予定"}}
