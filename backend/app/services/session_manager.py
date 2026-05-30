import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from app.models.transcript import SessionResult, TranscriptSegment
from app.db.store import SessionStore
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
        # session_id -> SessionResult (인메모리 캐시; 영속본은 SessionStore)
        self.sessions: dict[str, SessionResult] = {}
        self.store = SessionStore()
        # 백그라운드 GC 태스크 시작
        self._gc_task = None

    def init_store(self):
        """DB 초기화 + 기존 세션을 캐시로 적재 (lifespan에서 1회 호출)."""
        try:
            self.store.init()
            for s in self.store.load_all():
                self.sessions[s.session_id] = s
            logger.info(f"세션 영속 저장소 적재 완료: {len(self.sessions)}개 세션")
        except Exception as e:
            logger.error(f"세션 저장소 초기화 실패(인메모리로 계속): {e}")

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
        # 영속화 (메타)
        try:
            self.store.upsert_session(session)
        except Exception as e:
            logger.error(f"세션 생성 영속화 실패: {e}")
        return session

    def get_session(self, session_id: str) -> Optional[SessionResult]:
        """
        특정 세션 결과를 조회합니다. (캐시 미스 시 DB 폴백)
        """
        session = self.sessions.get(session_id)
        if session is None:
            session = self.store.get(session_id)
            if session is not None:
                self.sessions[session_id] = session  # 캐시 채움
        return session

    def list_sessions(self) -> list[SessionResult]:
        """영속본 기준 전체 세션 목록(생성 역순)."""
        try:
            return self.store.load_all()
        except Exception as e:
            logger.error(f"세션 목록 조회 실패(캐시 사용): {e}")
            return sorted(self.sessions.values(), key=lambda s: s.created_at, reverse=True)

    def delete_session(self, session_id: str) -> bool:
        """캐시 + 영속본 삭제."""
        existed = session_id in self.sessions or self.store.get(session_id) is not None
        self.sessions.pop(session_id, None)
        try:
            self.store.delete(session_id)
        except Exception as e:
            logger.error(f"세션 삭제 영속화 실패: {e}")
        return existed

    def update_session(self, session_id: str, **kwargs) -> Optional[SessionResult]:
        """
        세션의 필드 속성들을 업데이트합니다. (예: status, segments, speaker_count 등)
        세그먼트/상태 변경은 영속 저장소에도 write-through.
        """
        session = self.get_session(session_id)
        if session:
            for key, val in kwargs.items():
                if hasattr(session, key):
                    setattr(session, key, val)
            # 영속화: segments가 포함되면 전체 저장, 아니면 메타만
            try:
                if "segments" in kwargs:
                    self.store.save_full(session)
                else:
                    self.store.upsert_session(session)
            except Exception as e:
                logger.error(f"세션 업데이트 영속화 실패: {e}")
            return session
        return None

    def add_segment(self, session_id: str, segment: TranscriptSegment):
        """
        실시간 스트리밍 시 자막 세그먼트를 세션 목록에 지속적으로 추가합니다. (DB 증분 저장)
        """
        session = self.get_session(session_id)
        if session:
            seq = len(session.segments)
            session.segments.append(segment)
            # 고유 화자 수 재연산
            speakers = {seg.speaker for seg in session.segments}
            session.speaker_count = len(speakers)
            try:
                self.store.append_segment(session_id, segment, seq)
            except Exception as e:
                logger.error(f"세그먼트 영속화 실패: {e}")

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

                # 고아 세션 정리: stop 없이 버려져 'processing'에 멈춘 세션을 마감
                # (정상 종료는 명시적 stop에서 완료됨. 활동 종료 후 상한+여유 시간 경과 시 완료 처리)
                orphan_limit = now - timedelta(seconds=settings.MAX_SESSION_DURATION_SEC + 3600)
                try:
                    for s in self.store.load_all():
                        if s.status == "processing" and s.created_at < orphan_limit:
                            dur = max((seg.end for seg in s.segments), default=0.0)
                            self.update_session(
                                s.session_id, status="completed",
                                duration_sec=round(dur, 2),
                                speaker_count=len({seg.speaker for seg in s.segments if seg.speaker}),
                                segments=s.segments,
                            )
                            logger.info(f"🧹 고아 processing 세션 자동 완료 처리: {s.session_id}")
                except Exception as orphan_err:
                    logger.error(f"고아 세션 정리 실패: {orphan_err}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Session Manager GC loop: {e}")
