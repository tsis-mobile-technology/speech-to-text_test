import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from app.models.transcript import SessionResult, TranscriptSegment
from app.config import settings

logger = logging.getLogger(__name__)

class SessionManager:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
        
    def __init__(self):
        # session_id -> SessionResult
        self.sessions: dict[str, SessionResult] = {}
        # 백그라운드 GC 태스크 시작
        self._gc_task = None
        
    def start_gc_loop(self):
        """
        오래된 세션을 지우는 백그라운드 태스크를 실행합니다.
        """
        if self._gc_task is None:
            self._gc_task = asyncio.create_task(self._cleanup_expired_sessions_loop())
            logger.info("Session Manager GC background loop started.")

    def create_session(self, session_id: str) -> SessionResult:
        """
        새로운 STT 변환 세션을 생성하고 초기화합니다.
        """
        session = SessionResult(
            session_id=session_id,
            status="processing",
            created_at=datetime.now(),
            duration_sec=0.0,
            speaker_count=0,
            segments=[]
        )
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[SessionResult]:
        """
        특정 세션 결과를 조회합니다.
        """
        return self.sessions.get(session_id)

    def update_session(self, session_id: str, **kwargs) -> Optional[SessionResult]:
        """
        세션의 필드 속성들을 업데이트합니다. (예: status, segments, speaker_count 등)
        """
        session = self.get_session(session_id)
        if session:
            for key, val in kwargs.items():
                if hasattr(session, key):
                    setattr(session, key, val)
            return session
        return None

    def add_segment(self, session_id: str, segment: TranscriptSegment):
        """
        실시간 스트리밍 시 자막 세그먼트를 세션 목록에 지속적으로 추가합니다.
        """
        session = self.get_session(session_id)
        if session:
            session.segments.append(segment)
            # 고유 화자 수 재연산
            speakers = {seg.speaker for seg in session.segments}
            session.speaker_count = len(speakers)

    async def _cleanup_expired_sessions_loop(self):
        """
        주기적으로 (예: 1시간마다) TTL이 경과한 이전 세션 데이터를 삭제합니다.
        """
        while True:
            try:
                await asyncio.sleep(3600)  # 1시간 간격으로 스캔
                now = datetime.now()
                expiration_limit = now - timedelta(seconds=settings.SESSION_TTL_SECONDS)
                
                expired_ids = []
                for sid, session in list(self.sessions.items()):
                    if session.created_at < expiration_limit:
                        expired_ids.append(sid)
                        
                for sid in expired_ids:
                    del self.sessions[sid]
                    logger.info(f"Session {sid} expired and removed from memory cache.")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Session Manager GC loop: {e}")
