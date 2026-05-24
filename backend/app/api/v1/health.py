from fastapi import APIRouter
from app.utils.gpu_monitor import check_vram_usage, get_gpu_name

router = APIRouter()

@router.get("/health")
async def get_health_status():
    """
    백엔드 서버 헬스 체크용 엔드포인트
    """
    return {"status": "ok", "message": "STT system backend is running."}

@router.get("/health/gpu")
async def get_gpu_status():
    """
    로컬 GPU 정보 및 VRAM 모니터링 정보를 반환합니다.
    """
    used_mb, total_mb = check_vram_usage()
    gpu_name = get_gpu_name()
    return {
        "gpu_name": gpu_name,
        "vram_used_mb": used_mb,
        "vram_total_mb": total_mb,
        "vram_available_mb": max(0, total_mb - used_mb),
        "usage_percentage": round((used_mb / total_mb * 100), 2) if total_mb > 0 else 0.0
    }
