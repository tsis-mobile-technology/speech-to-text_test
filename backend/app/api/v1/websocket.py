import os
import uuid
import asyncio
import logging
import tempfile
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from scipy.io import wavfile
from app.services.session_manager import SessionManager
from app.core.audio_processor import AudioBufferProcessor
from app.core.stt_engine import STTEngine
from app.core.diarization import DiarizationEngine
from app.core.pipeline import align_segments
from app.models.transcript import TranscriptSegment
from app.utils.gpu_monitor import check_vram_usage

logger = logging.getLogger(__name__)
router = APIRouter()

def save_audio_buffer_to_file(audio_data: np.ndarray, sample_rate: int = 16000) -> str:
    """
    numpy float32 오디오 버퍼를 임시 WAV 파일로 디스크에 씁니다. (int16 PCM 형식)
    오디오 볼륨이 매우 작을 경우를 대비해 오디오 신호를 정규화(Normalize)하여 볼륨을 확보합니다.
    """
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, f"ws_session_{uuid.uuid4()}.wav")
    
    # 최댓값을 구하여 0.9 레벨로 노멀라이즈 (잡음만 있는 완전 무음 제외)
    max_val = np.max(np.abs(audio_data))
    if max_val > 1e-4:
        normalized = audio_data / max_val * 0.9
    else:
        normalized = audio_data
        
    # Float32 [-1.0, 1.0] -> Int16 변환
    clipped = np.clip(normalized, -1.0, 1.0)
    int_pcm = (clipped * 32767).astype(np.int16)
    
    wavfile.write(file_path, sample_rate, int_pcm)
    return file_path

@router.websocket("/ws/stream")
async def websocket_stt_stream(websocket: WebSocket):
    """
    실시간 바이너리 오디오 PCM 데이터를 스트리밍 받아 자막을 추출하는 WebSocket 엔드포인트입니다.
    연결 종료 시 전체 오디오에 대해 화자 분리(Diarization)를 수행하여 결과를 업데이트합니다.
    """
    await websocket.accept()
    
    session_id = str(uuid.uuid4())
    logger.info(f"WebSocket client connected. Assgined session: {session_id}")
    
    # 세션 매니저에 등록
    session_manager = SessionManager.get_instance()
    session_manager.create_session(session_id)
    
    audio_processor = AudioBufferProcessor()
    stt_engine = STTEngine.get_instance()
    diarizer = DiarizationEngine.get_instance()
    
    # 최초 연결 환영 응답 전송
    await websocket.send_json({
        "type": "info",
        "session_id": session_id,
        "message": "Connection established. Ready to receive audio stream."
    })
    
    # 실시간 처리 중 누적된 최종 결과 목록
    finalized_segments = []
    
    try:
        while True:
            # 바이너리 바이트 PCM 청크 수신
            message = await websocket.receive()
            
            if "bytes" in message:
                raw_bytes = message["bytes"]
                # 오디오 수집 버퍼에 충전 및 VAD 트리거 판정
                vad_triggered = audio_processor.append_chunk(raw_bytes)
                
                # VAD가 트리거되었거나 버퍼가 15초 이상 찬 경우 임시 전사 실행
                # (실시간 반응성 및 레이턴시 최소화를 위한 적정 간격 제어)
                audio_len = len(audio_processor.get_audio_data()) / 16000
                
                if vad_triggered or (audio_len > 0 and audio_len % 3.0 < 0.1):
                    # 1. 임시 WAV 파일 생성 (Whisper 추론용)
                    temp_wav = save_audio_buffer_to_file(audio_processor.get_audio_data())
                    
                    try:
                        # 2. Whisper 전사 수행 (실시간 처리를 위해 beam_size=1로 빠르게 연산)
                        # ThreadPoolExecutor에 의해 GPU 추론 직렬화 보장
                        whisper_results = await asyncio.get_event_loop().run_in_executor(
                            stt_engine.executor,
                            stt_engine._transcribe_sync,  # 동기 래퍼 직접 사용
                            temp_wav,
                            "ko"
                        )
                        
                        # VRAM 사용량 체크
                        vram_used, _ = check_vram_usage()
                        
                        # 3. 브라우저에 임시 실시간 자막 발송
                        if whisper_results:
                            # 임시 변환에서는 마지막 텍스트를 "partial" 또는 "final" 형태로 전송
                            # 여기서는 가장 최신 발화에 대해 partial 타입으로 브라우저에 실시간 업데이트 피드백 제공
                            for idx, raw_seg in enumerate(whisper_results):
                                is_last = (idx == len(whisper_results) - 1)
                                msg_type = "partial" if is_last else "final"
                                
                                seg_id = f"rt-{session_id}-{idx}"
                                trans_segment = TranscriptSegment(
                                    id=seg_id,
                                    session_id=session_id,
                                    start=raw_seg["start"],
                                    end=raw_seg["end"],
                                    text=raw_seg["text"],
                                    speaker="SPEAKER_00",  # 실시간 구간에서는 화자 지연 처리
                                    confidence=raw_seg["confidence"],
                                    is_final=(msg_type == "final")
                                )
                                
                                await websocket.send_json({
                                    "type": msg_type,
                                    "session_id": session_id,
                                    "segment": trans_segment.dict(),
                                    "gpu_usage_mb": vram_used
                                })
                                
                                if msg_type == "final":
                                    # 확정된 세그먼트는 임시 수집
                                    if seg_id not in [s.id for s in finalized_segments]:
                                        finalized_segments.append(trans_segment)
                                        session_manager.add_segment(session_id, trans_segment)
                                        
                    finally:
                        if os.path.exists(temp_wav):
                            os.remove(temp_wav)
                            
            elif "text" in message:
                # 텍스트 명령 수신 처리 (예: 녹음 강제 정지 등 제어)
                import json
                data = json.loads(message["text"])
                if data.get("command") == "stop":
                    logger.info("Client requested stream stop.")
                    break
                    
    except WebSocketDisconnect:
        logger.info(f"WebSocket session {session_id} disconnected by client.")
    except Exception as e:
        logger.error(f"Error in WebSocket streaming loop: {e}")
        await websocket.send_json({"type": "error", "session_id": session_id, "error": str(e)})
        
    # ==========================================================
    # 연결이 끊겼거나 중지 시 최종 후처리: Diarization (화자 분리)
    # ==========================================================
    logger.info(f"Performing final post-processing (Diarization) for session: {session_id}")
    
    full_audio = audio_processor.get_audio_data()
    if len(full_audio) > 16000: # 최소 1초 이상의 오디오가 누적되었을 때만 처리
        temp_full_wav = save_audio_buffer_to_file(full_audio)
        
        try:
            # 1. 전체 오디오에 대해 한 번 더 최종 Whisper 전사 정밀 수행 (beam_size=5)
            whisper_results = await stt_engine.transcribe(temp_full_wav, language="ko")
            
            # 2. pyannote 화자 분리 1회 전체 실행
            # ThreadPoolExecutor에 의해 GPU 추론 직렬화 보장
            diarization_results = await diarizer.diarize(temp_full_wav)
            
            # 3. 시간 오버랩 기준으로 Whisper 전사 자막과 화자 분리 데이터 매핑 정렬
            final_segments = align_segments(whisper_results, diarization_results, session_id)
            
            # 4. 세션 최종 결과 업데이트 및 저장
            unique_speakers = {seg.speaker for seg in final_segments}
            session_manager.update_session(
                session_id,
                status="completed",
                duration_sec=round(len(full_audio)/16000, 2),
                speaker_count=len(unique_speakers),
                segments=final_segments
            )
            
            # 5. 브라우저가 아직 살아있을 경우(강제 stop 명령 등으로 수동 정지된 경우)
            # 최종 정렬 완료된 전체 리스트를 "speaker_updated" 메시지로 클라이언트에 전달
            try:
                await websocket.send_json({
                    "type": "speaker_updated",
                    "session_id": session_id,
                    "message": "Final transcription and speaker diarization aligned successfully.",
                    "segments": [seg.dict() for seg in final_segments]
                })
            except Exception:
                # 연결이 완전히 끊긴 경우 예외 무시
                pass
                
            logger.info(f"Final post-processing complete for session: {session_id}")
            
        except Exception as ex:
            logger.error(f"Failed to perform post-diarization process: {ex}")
            session_manager.update_session(session_id, status="failed", error_message=str(ex))
        finally:
            if os.path.exists(temp_full_wav):
                os.remove(temp_full_wav)
    else:
        logger.warning(f"Audio buffer too short to finalize session: {session_id}")
        session_manager.update_session(session_id, status="completed", segments=[])
