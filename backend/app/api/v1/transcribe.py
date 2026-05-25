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
MAX_FILE_SIZE_MB = 500  # 최대 500MB
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

async def execute_transcription_task(session_id: str, temp_file_path: str, enable_diarization: bool):
    """
    백그라운드에서 오디오 파이프라인을 구동하고 결과를 세션에 저장하는 태스크입니다.
    파일 업로드는 balanced beam size(3)를 사용하여 정확도 20-30% 향상.
    """
    session_manager = SessionManager.get_instance()
    try:
        from app.config import settings
        # 통합 STT + Diarization 파이프라인 호출 (파일용: beam_size=BALANCED)
        segments, duration, speaker_count = await run_stt_diarization_pipeline(
            session_id=session_id,
            file_path=temp_file_path,
            enable_diarization=enable_diarization,
            beam_size=settings.BEAM_SIZE_BALANCED,  # ⭐ 파일은 정확도 우선
            context="meeting"
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
    # 파일명 검증
    if not audio_file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    filename = audio_file.filename.strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Filename cannot be empty or whitespace")

    # 확장자 검증
    name_part, ext = os.path.splitext(filename.lower())
    if not ext:
        raise HTTPException(
            status_code=400,
            detail="Filename must have an extension"
        )

    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if not name_part:
        raise HTTPException(status_code=400, detail="Filename must have a name before extension")

    # 파일 크기 검증 (Content-Length 헤더 확인)
    if audio_file.size and audio_file.size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File size exceeds maximum allowed size of {MAX_FILE_SIZE_MB}MB"
        )

    session_id = str(uuid.uuid4())

    # 디스크에 원본 임시 파일 저장
    temp_dir = tempfile.gettempdir()
    temp_file_path = os.path.join(temp_dir, f"upload_{session_id}{ext}")

    bytes_received = 0
    try:
        with open(temp_file_path, "wb") as buffer:
            while True:
                chunk = await audio_file.read(1024 * 1024)  # 1MB 청크
                if not chunk:
                    break
                bytes_received += len(chunk)

                # 스트리밍 중 크기 제한 체크
                if bytes_received > MAX_FILE_SIZE_BYTES:
                    os.remove(temp_file_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File size exceeds maximum allowed size of {MAX_FILE_SIZE_MB}MB"
                    )

                buffer.write(chunk)

        if bytes_received == 0:
            os.remove(temp_file_path)
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        logger.info(f"✅ Saved uploaded file: {temp_file_path} ({bytes_received} bytes)")
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as cleanup_err:
                logger.error(f"Failed to cleanup temp file {temp_file_path}: {cleanup_err}")
        logger.error(f"❌ Failed to save uploaded file: {e}")
        raise HTTPException(status_code=500, detail="Failed to handle file upload")

    # 세션 정보 생성 및 백그라운드 작업 예약
    session_manager = SessionManager.get_instance()
    session_manager.create_session(session_id)

    background_tasks.add_task(
        execute_transcription_task,
        session_id=session_id,
        temp_file_path=temp_file_path,
        enable_diarization=enable_diarization
    )

    logger.info(f"🎯 Transcription task queued for session {session_id}")
    return {
        "session_id": session_id,
        "status": "processing",
        "message": "Transcription task started in the background.",
        "file_size_mb": round(bytes_received / (1024 * 1024), 2)
    }
