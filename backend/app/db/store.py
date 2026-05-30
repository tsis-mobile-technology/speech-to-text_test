import sqlite3
import logging
import threading
from datetime import datetime
from typing import Optional
from app.config import settings
from app.models.transcript import SessionResult, TranscriptSegment

logger = logging.getLogger(__name__)


class SessionStore:
    """
    SQLite 기반 세션/세그먼트 영속 저장소 (stdlib sqlite3, 신규 의존성 없음).
    - 회의 메타 + 세그먼트만 DB에 저장(오디오 대용량은 파일시스템, 경로만 보관).
    - 단일 노드·저동시(동시 3, GPU 직렬화) 환경에 적합. 쓰기는 lock으로 직렬화.
    인메모리 캐시(SessionManager)와 함께 write-through로 사용된다.
    """

    def __init__(self, db_path: str = None):
        self.db_path = str(db_path or settings.DB_PATH)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def init(self):
        """디렉터리/테이블을 준비한다. lifespan에서 1회 호출."""
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        settings.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    status TEXT,
                    created_at TEXT,
                    duration_sec REAL,
                    speaker_count INTEGER,
                    audio_language TEXT,
                    audio_path TEXT,
                    error_message TEXT
                );
                CREATE TABLE IF NOT EXISTS segments (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    seq INTEGER,
                    start REAL,
                    end REAL,
                    text TEXT,
                    speaker TEXT,
                    confidence REAL,
                    is_final INTEGER,
                    detected_language TEXT,
                    no_speech_prob REAL,
                    original_text TEXT,
                    corrected INTEGER,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_segments_session ON segments(session_id, seq);
                CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at);
                """
            )
            self._conn.commit()
        logger.info(f"SessionStore initialized at {self.db_path}")

    # ---- 내부 헬퍼 ----
    def _upsert_session_row(self, s: SessionResult):
        self._conn.execute(
            """
            INSERT INTO sessions(session_id,status,created_at,duration_sec,speaker_count,audio_language,audio_path,error_message)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET
              status=excluded.status, duration_sec=excluded.duration_sec,
              speaker_count=excluded.speaker_count, audio_language=excluded.audio_language,
              audio_path=excluded.audio_path, error_message=excluded.error_message
            """,
            (
                s.session_id, s.status, s.created_at.isoformat(),
                s.duration_sec, s.speaker_count, s.audio_language,
                getattr(s, "audio_path", None), s.error_message,
            ),
        )

    def _seg_row(self, sid: str, seq: int, seg: TranscriptSegment):
        return (
            seg.id, sid, seq, seg.start, seg.end, seg.text, seg.speaker,
            seg.confidence, 1 if seg.is_final else 0, seg.detected_language,
            seg.no_speech_prob, seg.original_text, 1 if seg.corrected else 0,
        )

    # ---- 공개 API (write-through) ----
    def upsert_session(self, s: SessionResult):
        """메타만 갱신(세그먼트 미변경)."""
        if self._conn is None:
            return
        with self._lock:
            self._upsert_session_row(s)
            self._conn.commit()

    def append_segment(self, session_id: str, seg: TranscriptSegment, seq: int):
        """실시간 세그먼트 1건 영속(중복 id는 무시)."""
        if self._conn is None:
            return
        with self._lock:
            self._conn.execute(
                """INSERT OR IGNORE INTO segments
                (id,session_id,seq,start,end,text,speaker,confidence,is_final,detected_language,no_speech_prob,original_text,corrected)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                self._seg_row(session_id, seq, seg),
            )
            self._conn.commit()

    def save_full(self, s: SessionResult):
        """세션 메타 + 전체 세그먼트를 한 트랜잭션으로 저장(세그먼트 교체)."""
        if self._conn is None:
            return
        with self._lock:
            self._upsert_session_row(s)
            self._conn.execute("DELETE FROM segments WHERE session_id=?", (s.session_id,))
            self._conn.executemany(
                """INSERT OR REPLACE INTO segments
                (id,session_id,seq,start,end,text,speaker,confidence,is_final,detected_language,no_speech_prob,original_text,corrected)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [self._seg_row(s.session_id, i, seg) for i, seg in enumerate(s.segments)],
            )
            self._conn.commit()

    def get(self, session_id: str) -> Optional[SessionResult]:
        if self._conn is None:
            return None
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if not row:
                return None
            seg_rows = self._conn.execute(
                "SELECT * FROM segments WHERE session_id=? ORDER BY seq", (session_id,)
            ).fetchall()
        return self._row_to_session(row, seg_rows)

    def load_all(self) -> list[SessionResult]:
        if self._conn is None:
            return []
        with self._lock:
            srows = self._conn.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
            results = []
            for row in srows:
                seg_rows = self._conn.execute(
                    "SELECT * FROM segments WHERE session_id=? ORDER BY seq", (row["session_id"],)
                ).fetchall()
                results.append(self._row_to_session(row, seg_rows))
        return results

    def delete(self, session_id: str):
        if self._conn is None:
            return
        with self._lock:
            self._conn.execute("DELETE FROM segments WHERE session_id=?", (session_id,))
            self._conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            self._conn.commit()

    def _row_to_session(self, row, seg_rows) -> SessionResult:
        segments = [
            TranscriptSegment(
                id=r["id"], session_id=r["session_id"], start=r["start"], end=r["end"],
                text=r["text"], speaker=r["speaker"], confidence=r["confidence"],
                is_final=bool(r["is_final"]), detected_language=r["detected_language"] or "unknown",
                no_speech_prob=r["no_speech_prob"], original_text=r["original_text"],
                corrected=bool(r["corrected"]),
            )
            for r in seg_rows
        ]
        try:
            created = datetime.fromisoformat(row["created_at"])
        except (ValueError, TypeError):
            created = datetime.now()
        return SessionResult(
            session_id=row["session_id"], status=row["status"], created_at=created,
            duration_sec=row["duration_sec"] or 0.0, speaker_count=row["speaker_count"] or 0,
            segments=segments, audio_language=row["audio_language"] or "ko",
            error_message=row["error_message"], audio_path=row["audio_path"],
        )
