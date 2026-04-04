"""解析API（/api/analysis）- PHASE 3で完全実装"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/analysis/descriptive")
def get_descriptive(player_id: int):
    """記述統計（TASK-030で実装）"""
    return {"success": True, "data": {}, "meta": {"sample_size": 0}}


@router.get("/analysis/heatmap")
def get_heatmap(player_id: int, type: str = "hit"):
    """ヒートマップ（TASK-031で実装）"""
    return {"success": True, "data": {}}


@router.get("/analysis/markov")
def get_markov(player_id: int):
    """マルコフ連鎖+EPV（TASK-032で実装）"""
    return {"success": True, "data": {}}


@router.get("/analysis/confidence")
def get_confidence(player_id: int, analysis_type: str):
    """信頼度評価"""
    return {"success": True, "data": {"stars": "★☆☆", "label": "参考値（データ蓄積中）"}}
