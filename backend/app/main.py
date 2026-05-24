import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.stt_engine import STTEngine
from app.core.diarization import DiarizationEngine
from app.services.session_manager import SessionManager

from app.api.v1.transcribe import router as transcribe_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.health import router as health_router
from app.api.v1.websocket import router as ws_router

# 로깅 기본 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    서버 시작 시 AI 모델들을 GPU에 사전 탑재하여 콜드 스타트를 제거하고,
    백그라운드 세션 메모리 수거(GC) 루프를 실행합니다.
    """
    logger.info("Initializing STT Meeting system backend...")
    
    # 1. 인메모리 세션 GC 데몬 시작
    session_manager = SessionManager.get_instance()
    session_manager.start_gc_loop()
    
    # 2. faster-whisper 모델 사전 메모리(VRAM) 탑재
    stt = STTEngine.get_instance()
    stt.load_model()
    
    # 3. pyannote.audio 화자분리 모델 사전 메모리 탑재
    diarizer = DiarizationEngine.get_instance()
    diarizer.load_model()
    
    logger.info("Startup sequence completed. Models are loaded in GPU memory.")
    yield
    
    # 서버 종료 시 VRAM 자원 정리 해제
    logger.info("Shutdown sequence initiated. Cleaning up VRAM models...")
    stt.release()
    diarizer.release()
    logger.info("Server cleanup completed.")

# FastAPI 애플리케이션 정의
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="NVIDIA GPU 가속 온프레미스 한국어 STT 및 화자분리 회의록 변환 FastAPI 백엔드",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 허용 정책 설정 (Next.js 로컬 구동 주소 3000포트 접근 대응)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 실무에서는 특정 도메인만 지정 권장
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API v1 라우터 매핑 등록
app.include_router(health_router, prefix="/api/v1", tags=["Health"])
app.include_router(transcribe_router, prefix="/api/v1", tags=["Transcribe"])
app.include_router(sessions_router, prefix="/api/v1", tags=["Sessions"])
app.include_router(ws_router, prefix="/api/v1", tags=["Realtime WebSocket"])

@app.get("/")
async def root_redirect():
    """
    루트 엔드포인트: 헬스 및 정보 반환
    """
    return {
        "project": settings.PROJECT_NAME,
        "api_documentation": "/docs",
        "health_check": "/api/v1/health"
    }
