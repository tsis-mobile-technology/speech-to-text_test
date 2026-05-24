from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from io import BytesIO
from app.services.session_manager import SessionManager
from app.services.export_service import export_to_srt, export_to_txt, export_to_json, export_to_docx

router = APIRouter()

class SegmentUpdateRequest(BaseModel):
    text: str
    speaker: str

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
    session_manager = SessionManager.get_instance()
    session = session_manager.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "completed":
        raise HTTPException(status_code=400, detail="Session is not completed yet")

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

@router.put("/sessions/{session_id}/segments/{segment_id}")
async def update_transcript_segment(
    session_id: str,
    segment_id: str,
    payload: SegmentUpdateRequest
):
    """
    에디터에서 사용자가 수정한 특정 구간의 자막 텍스트와 화자 레이블을 세션 데이터에 반영합니다.
    """
    session_manager = SessionManager.get_instance()
    session = session_manager.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    for segment in session.segments:
        if segment.id == segment_id:
            segment.text = payload.text.strip()
            segment.speaker = payload.speaker.strip()
            
            # 고유 화자수 재연산
            speakers = {seg.speaker for seg in session.segments}
            session.speaker_count = len(speakers)
            return {"status": "success", "segment": segment}
            
    raise HTTPException(status_code=404, detail="Segment not found in session")
