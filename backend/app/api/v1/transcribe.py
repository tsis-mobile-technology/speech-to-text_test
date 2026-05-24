import os
import uuid
import shutil
import tempfile
import logging
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException
from app.services.session_manager import SessionManager
from app.core.pipeline import run_stt_diarization_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4", ".ogg", ".webm", ".flac"}

async def execute_transcription_task(session_id: str, temp_file_path: str, enable_diarization: bool):
    """
    백그라운드에서 오디오 파이프라인을 구동하고 결과를 세션에 저장하는 태스크입니다.
    """
    session_manager = SessionManager.get_instance()
    try:
        # 통합 STT + Diarization 파이프라인 호출
        segments, duration, speaker_count = await run_stt_diarization_pipeline(
            session_id=session_id,
            file_path=temp_file_path,
            enable_diarization=enable_diarization
        )
        
        # 완료 상태로 세션 업데이트
        session_manager.update_session(
            session_id,
            status="completed",
            duration_sec=duration,
            speaker_count=speaker_count,
            segments=segments
        )
        logger.info(f"Background transcription task succeeded for session {session_id}")
    except Exception as e:
        logger.error(f"Background transcription task failed for session {session_id}: {e}")
        session_manager.update_session(
            session_id,
            status="failed",
            error_message=str(e)
        )
    finally:
        # 업로드된 원본 임시 파일 삭제
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info(f"Removed temp uploaded file: {temp_file_path}")
            except OSError as e:
                logger.error(f"Failed to remove temp file {temp_file_path}: {e}")

@router.post("/transcribe")
async def transcribe_audio_file(
    background_tasks: BackgroundTasks,
    audio_file: UploadFile = File(...),
    enable_diarization: bool = Form(True)
):
    """
    음성 오디오 파일을 업로드하여 텍스트 및 화자분리 회의록 변환 작업을 백그라운드에 등록합니다.
    """
    filename = audio_file.filename
    _, ext = os.path.splitext(filename.lower())
    
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
        
    session_id = str(uuid.uuid4())
    
    # 디스크에 원본 임시 파일 저장
    temp_dir = tempfile.gettempdir()
    temp_file_path = os.path.join(temp_dir, f"upload_{session_id}{ext}")
    
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(audio_file.file, buffer)
        logger.info(f"Successfully saved uploaded file to {temp_file_path}")
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        raise HTTPException(status_code=500, detail="Failed to handle file upload.")
    
    # 세션 정보 생성 및 백그라운드 작업 예약
    session_manager = SessionManager.get_instance()
    session_manager.create_session(session_id)
    
    background_tasks.add_task(
        execute_transcription_task,
        session_id=session_id,
        temp_file_path=temp_file_path,
        enable_diarization=enable_diarization
    )
    
    # 대략적인 변환 추정치 (파일 업로드 즉시 완료 처리를 기다리지 않고 반환)
    return {
        "session_id": session_id,
        "status": "processing",
        "message": "Transcription task started in the background."
    }
