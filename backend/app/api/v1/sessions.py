from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, validator
from io import BytesIO
import logging
from app.services.session_manager import SessionManager
from app.services.export_service import export_to_srt, export_to_txt, export_to_json, export_to_docx

logger = logging.getLogger(__name__)
router = APIRouter()

class SegmentUpdateRequest(BaseModel):
    text: str
    speaker: str

    @validator('text')
    def text_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Text cannot be empty')
        return v.strip()

    @validator('speaker')
    def speaker_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Speaker cannot be empty')
        return v.strip()

@router.get("/sessions", tags=["Sessions"])
async def list_sessions():
    """
    현재 메모리 상에 존재하는 모든 회의록 세션 목록을 반환합니다.

    Returns:
        List[SessionResult]: 생성 시간 역순으로 정렬된 세션 목록
    """
    session_manager = SessionManager.get_instance()
    # 생성 시간 역순으로 정렬하여 반환
    sorted_sessions = sorted(
        session_manager.sessions.values(),
        key=lambda s: s.created_at,
        reverse=True
    )
    logger.info(f"Listed {len(sorted_sessions)} sessions")
    return sorted_sessions

@router.get("/sessions/{session_id}")
async def get_session_status(session_id: str):
    """
    회의록 세션의 진행 상태와 결과 세그먼트를 반환합니다.
    """
    session_manager = SessionManager.get_instance()
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    메모리 캐시에서 특정 회의록 세션을 삭제합니다.
    """
    session_manager = SessionManager.get_instance()
    if session_id in session_manager.sessions:
        del session_manager.sessions[session_id]
        return {"status": "success", "message": f"Session {session_id} deleted successfully."}
    raise HTTPException(status_code=404, detail="Session not found")

@router.get("/sessions/{session_id}/export")
async def export_session_transcript(
    session_id: str,
    format: str = Query("srt", regex="^(srt|txt|json|docx)$")
):
    """
    회의록 변환 데이터를 SRT, TXT, JSON, DOCX 포맷 파일로 내보냅니다.

    Query Parameters:
    - format: srt|txt|json|docx (기본값: srt)

    Returns:
    - SRT: 자막 파일 (타임스탐프 포함)
    - TXT: 일반 텍스트 회의록
    - JSON: 구조화된 메타데이터 포함 JSON
    - DOCX: Microsoft Word 문서 (python-docx 필요)
    """
    # 세션 ID 유효성 검사
    if not session_id or not session_id.strip():
        raise HTTPException(status_code=400, detail="Invalid session ID")

    session_manager = SessionManager.get_instance()
    session = session_manager.get_session(session_id)

    if not session:
        logger.warning(f"Export requested for non-existent session: {session_id}")
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if session.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Session is not completed yet. Current status: {session.status}"
        )

    # 빈 세그먼트 확인
    if not session.segments or len(session.segments) == 0:
        logger.warning(f"Export requested for session with no segments: {session_id}")
        raise HTTPException(
            status_code=400,
            detail="Session has no transcript segments to export"
        )

    try:
        if format == "srt":
            content = export_to_srt(session.segments)
            return PlainTextResponse(
                content,
                headers={"Content-Disposition": f"attachment; filename=transcript_{session_id}.srt"}
            )
        elif format == "txt":
            content = export_to_txt(session.segments)
            return PlainTextResponse(
                content,
                headers={
                    "Content-Disposition": f"attachment; filename=transcript_{session_id}.txt",
                    "charset": "utf-8"
                }
            )
        elif format == "json":
            content = export_to_json(session)
            return PlainTextResponse(
                content,
                media_type="application/json; charset=utf-8",
                headers={"Content-Disposition": f"attachment; filename=transcript_{session_id}.json"}
            )
        elif format == "docx":
            try:
                content = export_to_docx(session)
                return StreamingResponse(
                    iter([content]),
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f"attachment; filename=transcript_{session_id}.docx"}
                )
            except ImportError:
                raise HTTPException(
                    status_code=501,
                    detail="DOCX export requires python-docx. Install with: pip install python-docx"
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Export failed for session {session_id} (format={format}): {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Export failed: {str(e)}"
        )

@router.put("/sessions/{session_id}/segments/{segment_id}")
async def update_transcript_segment(
    session_id: str,
    segment_id: str,
    payload: SegmentUpdateRequest
):
    """
    에디터에서 사용자가 수정한 특정 구간의 자막 텍스트와 화자 레이블을 세션 데이터에 반영합니다.
    """
    # 입력값 검증
    if not session_id or not session_id.strip():
        raise HTTPException(status_code=400, detail="Invalid session ID")

    if not segment_id or not segment_id.strip():
        raise HTTPException(status_code=400, detail="Invalid segment ID")

    session_manager = SessionManager.get_instance()
    session = session_manager.get_session(session_id)

    if not session:
        logger.warning(f"Update segment requested for non-existent session: {session_id}")
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if not session.segments:
        raise HTTPException(status_code=400, detail="Session has no segments")

    # 세그먼트 검색 및 업데이트
    updated_segment = None
    for segment in session.segments:
        if segment.id == segment_id:
            old_text = segment.text
            old_speaker = segment.speaker

            segment.text = payload.text
            segment.speaker = payload.speaker

            # 고유 화자수 재연산
            speakers = {seg.speaker for seg in session.segments if seg.speaker}
            session.speaker_count = len(speakers)

            updated_segment = segment
            logger.info(
                f"Updated segment {segment_id} in session {session_id}: "
                f"speaker {old_speaker}→{payload.speaker}"
            )
            break

    if not updated_segment:
        logger.warning(f"Segment {segment_id} not found in session {session_id}")
        raise HTTPException(
            status_code=404,
            detail=f"Segment '{segment_id}' not found in session"
        )

    return {
        "status": "success",
        "segment": updated_segment,
        "speaker_count": session.speaker_count
    }
