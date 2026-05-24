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
    try:
        await websocket.accept()
        logger.info("✅ WebSocket accepted")

        session_id = str(uuid.uuid4())
        logger.info(f"🆔 WebSocket client connected. Session: {session_id}")

        # 세션 매니저에 등록
        session_manager = SessionManager.get_instance()
        session_manager.create_session(session_id)
        logger.info(f"📋 Session created: {session_id}")

        audio_processor = AudioBufferProcessor()
        stt_engine = STTEngine.get_instance()
        diarizer = DiarizationEngine.get_instance()
        logger.info("🔧 Engines initialized")

        # 최초 연결 환영 응답 전송
        logger.info("📤 Sending welcome message...")
        await websocket.send_json({
            "type": "info",
            "session_id": session_id,
            "message": "Connection established. Ready to receive audio stream."
        })
        logger.info("✅ Welcome message sent")
    except Exception as e:
        logger.error(f"❌ Error during WebSocket setup: {e}")
        raise
    
    # 실시간 처리 중 누적된 최종 결과 목록
    finalized_segments = []
    processing_count = 0  # 처리 횟수 (고유 ID 생성용)

    try:
        while True:
            try:
                # 바이너리 바이트 PCM 청크 수신
                logger.debug(f"Waiting for message from client...")
                message = await websocket.receive()
                logger.debug(f"Message received: {list(message.keys())}")

            except asyncio.CancelledError:
                logger.warning(f"WebSocket task cancelled for session {session_id}")
                raise
            except Exception as recv_err:
                logger.error(f"Error receiving message: {recv_err}")
                raise

            if "bytes" in message:
                raw_bytes = message["bytes"]
                # 오디오 수집 버퍼에 충전 및 VAD 트리거 판정
                vad_triggered = audio_processor.append_chunk(raw_bytes)
                logger.debug(f"Audio chunk received: {len(raw_bytes)} bytes, VAD triggered: {vad_triggered}")
                
                # VAD 트리거로만 임시 전사 실행 (이미 2초 무음 대기로 최적화됨)
                # 일정 간격 트리거는 제거하여 불필요한 공백 처리 방지
                if vad_triggered:
                    # 1. 임시 WAV 파일 생성 (Whisper 추론용)
                    import time
                    start_time = time.time()
                    temp_wav = save_audio_buffer_to_file(audio_processor.get_audio_data())

                    try:
                        # 2. Whisper 전사 수행 (실시간 처리를 위해 beam_size=1로 빠르게 연산)
                        # ThreadPoolExecutor에 의해 GPU 추론 직렬화 보장
                        whisper_start = time.time()
                        whisper_results = await asyncio.get_event_loop().run_in_executor(
                            stt_engine.executor,
                            stt_engine._transcribe_sync,  # 동기 래퍼 직접 사용
                            temp_wav,
                            "ko"
                        )
                        whisper_time = time.time() - whisper_start

                        # VRAM 사용량 체크
                        vram_used, _ = check_vram_usage()
                        total_time = time.time() - start_time
                        logger.info(f"⏱️ 처리 시간: {total_time*1000:.0f}ms (Whisper: {whisper_time*1000:.0f}ms, VRAM: {vram_used}MB)")

                        # 3. 브라우저에 실시간 자막 발송
                        if whisper_results and len(whisper_results) > 0:
                            logger.info(f"📤 Sending {len(whisper_results)} segments to client")
                            processing_count += 1
                            segment_count = 0

                            for idx, raw_seg in enumerate(whisper_results):
                                # 세그먼트 검증
                                if not raw_seg or not isinstance(raw_seg, dict):
                                    logger.warning(f"⚠️ Skipping invalid segment at index {idx}")
                                    continue

                                if not raw_seg.get("text") or not str(raw_seg.get("text")).strip():
                                    logger.debug(f"⚠️ Skipping empty text segment at index {idx}")
                                    continue

                                seg_id = f"rt-{session_id}-{processing_count}-{idx}"
                                try:
                                    trans_segment = TranscriptSegment(
                                        id=seg_id,
                                        session_id=session_id,
                                        start=float(raw_seg.get("start", 0)),
                                        end=float(raw_seg.get("end", 0)),
                                        text=str(raw_seg.get("text", "")).strip(),
                                        speaker="SPEAKER_00",
                                        confidence=float(raw_seg.get("confidence", 0)),
                                        is_final=True
                                    )

                                    await websocket.send_json({
                                        "type": "final",
                                        "session_id": session_id,
                                        "segment": trans_segment.dict(),
                                        "gpu_usage_mb": vram_used
                                    })
                                    logger.info(f"✅ Sent final: {trans_segment.text[:50]}")

                                    # 중복 확인 후 저장
                                    if seg_id not in [s.id for s in finalized_segments]:
                                        finalized_segments.append(trans_segment)
                                        session_manager.add_segment(session_id, trans_segment)
                                        segment_count += 1
                                    else:
                                        logger.debug(f"⚠️ Duplicate segment ignored: {seg_id}")

                                except ValueError as val_err:
                                    logger.error(f"❌ Invalid segment data at {idx}: {val_err}")
                                    continue
                                except Exception as send_err:
                                    logger.error(f"❌ Failed to send segment {seg_id}: {send_err}")
                                    raise

                            if segment_count == 0:
                                logger.warning(f"⚠️ No valid segments to send (all filtered)")
                        else:
                            logger.debug(f"⚠️ No whisper results (empty array or None)")

                        # Whisper 처리 완료 후 버퍼 초기화 (중복 처리 방지)
                        audio_processor.clear()
                        logger.debug(f"🗑️ Audio buffer cleared after processing")

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
    logger.info(f"🔄 Final post-processing (Diarization) for session: {session_id}")

    full_audio = audio_processor.get_audio_data()
    min_audio_samples = 16000  # 최소 1초 (16kHz)

    if full_audio is None or len(full_audio) == 0:
        logger.warning(f"⚠️ No audio data collected for session {session_id}")
        session_manager.update_session(
            session_id,
            status="completed",
            duration_sec=0,
            speaker_count=0,
            segments=[]
        )
        return

    if len(full_audio) < min_audio_samples:
        logger.warning(
            f"⚠️ Audio too short ({len(full_audio)} samples, need {min_audio_samples}). "
            f"Finalizing with existing segments."
        )
        unique_speakers = {seg.speaker for seg in finalized_segments if seg.speaker}
        session_manager.update_session(
            session_id,
            status="completed",
            duration_sec=round(len(full_audio) / 16000, 2),
            speaker_count=len(unique_speakers),
            segments=finalized_segments
        )
        return

    temp_full_wav = None
    try:
        temp_full_wav = save_audio_buffer_to_file(full_audio)
        logger.info(f"📁 Created temp WAV for diarization: {temp_full_wav}")

        # 1. 최종 Whisper 전사 (beam_size=5)
        try:
            whisper_results = await stt_engine.transcribe(temp_full_wav, language="ko")
            if not whisper_results:
                logger.warning(f"⚠️ No Whisper results for final processing")
                whisper_results = []
        except Exception as whisper_err:
            logger.error(f"❌ Whisper transcription failed: {whisper_err}")
            whisper_results = []

        # 2. pyannote 화자 분리
        try:
            diarization_results = await diarizer.diarize(temp_full_wav)
            if not diarization_results:
                logger.warning(f"⚠️ No diarization results")
                diarization_results = []
        except Exception as diar_err:
            logger.error(f"❌ Diarization failed: {diar_err}")
            diarization_results = []

        # 3. 세그먼트 정렬 (둘 다 실패했을 수도 있음)
        try:
            final_segments = align_segments(whisper_results, diarization_results, session_id)
            if not final_segments:
                logger.info(f"ℹ️ Using previously finalized segments ({len(finalized_segments)})")
                final_segments = finalized_segments
        except Exception as align_err:
            logger.error(f"❌ Alignment failed: {align_err}")
            final_segments = finalized_segments

        # 4. 세션 완료 처리
        unique_speakers = {seg.speaker for seg in final_segments if seg.speaker}
        session_manager.update_session(
            session_id,
            status="completed",
            duration_sec=round(len(full_audio) / 16000, 2),
            speaker_count=len(unique_speakers),
            segments=final_segments
        )
        logger.info(
            f"✅ Session {session_id} completed: "
            f"{len(final_segments)} segments, {len(unique_speakers)} speakers"
        )

        # 5. 클라이언트에 최종 결과 전송
        if final_segments:
            try:
                await websocket.send_json({
                    "type": "speaker_updated",
                    "session_id": session_id,
                    "message": "Final transcription and diarization complete.",
                    "segments": [seg.dict() for seg in final_segments]
                })
                logger.info(f"📤 Sent speaker_updated message to client")
            except Exception as send_err:
                logger.debug(f"ℹ️ Client connection closed before final message: {send_err}")
        else:
            logger.warning(f"⚠️ No segments to send to client")

    except Exception as ex:
        logger.error(f"❌ Post-processing failed: {ex}", exc_info=True)
        session_manager.update_session(
            session_id,
            status="failed",
            error_message=f"Post-processing error: {str(ex)}"
        )
    finally:
        if temp_full_wav and os.path.exists(temp_full_wav):
            try:
                os.remove(temp_full_wav)
                logger.debug(f"🗑️ Removed temp WAV file")
            except OSError as cleanup_err:
                logger.error(f"Failed to remove temp file: {cleanup_err}")
