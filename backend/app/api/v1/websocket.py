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
from app.core.llm_corrector import LLMCorrector
from app.core.pipeline import align_segments, assign_speakers
from app.config import settings
from app.models.transcript import TranscriptSegment
from app.utils.gpu_monitor import check_vram_usage
from app.utils.audio import get_audio_duration

logger = logging.getLogger(__name__)
router = APIRouter()

# 현재 활성 WebSocket 세션 ID (동일 세션 중복 연결 방지용)
_active_ws_sessions: set = set()

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

        # 클라이언트가 회의 단위 세션 ID를 지정(재연결 시 동일 ID로 이어쓰기). 없으면 신규 생성.
        client_session_id = websocket.query_params.get("session_id")
        session_id = client_session_id or str(uuid.uuid4())

        # 동일 세션 동시 연결 가드 (한 회의에 활성 연결 1개만 허용)
        if session_id in _active_ws_sessions:
            logger.warning(f"⚠️ 동일 세션 중복 연결 거부: {session_id}")
            await websocket.send_json({
                "type": "error", "session_id": session_id,
                "error": "이미 활성화된 동일 세션 연결이 있습니다."
            })
            await websocket.close()
            return
        _active_ws_sessions.add(session_id)

        session_manager = SessionManager.get_instance()
        existing = session_manager.get_session(session_id)
        resumed = bool(existing and existing.status != "completed" and existing.segments is not None)
        if not existing:
            session_manager.create_session(session_id)
            logger.info(f"📋 Session created: {session_id}")
        elif resumed:
            session_manager.update_session(session_id, status="processing")
            logger.info(f"♻️ Session resumed: {session_id} ({len(existing.segments)} segments)")
        else:
            logger.info(f"📋 Session re-opened (was completed): {session_id}")

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
        logger.error(f"Error during WebSocket setup: {e}")
        if 'session_id' in locals():
            _active_ws_sessions.discard(session_id)
            try:
                SessionManager.get_instance().update_session(
                    session_id,
                    status="failed",
                    error_message=f"Setup error: {str(e)}"
                )
            except Exception as update_err:
                logger.error(f"Failed to update session status on setup error: {update_err}")
        raise
    
    # 실시간 처리 중 누적된 최종 결과 목록 (= 전체 회의록, 절대 비우지 않음)
    # 재연결 이어쓰기: 기존 세션이면 누적 세그먼트 복원
    finalized_segments = list(existing.segments) if resumed else []
    processing_count = 0  # 처리 횟수 (고유 ID 생성용)
    conn_nonce = uuid.uuid4().hex[:6]  # 연결마다 고유 → 재연결 시 세그먼트 ID 충돌 방지
    finalize_requested = False  # True일 때만(명시적 stop) 종료 후처리·완료 저장

    # Tier 2: 전체 회의 연속 타임라인용 전역 오프셋(초)
    global_offset_sec = 0.0

    # LLM 보정 논블로킹 처리용: 동시 send 충돌 방지 lock + 진행중 태스크 추적
    send_lock = asyncio.Lock()
    correction_tasks: set = set()

    async def _ws_send(payload: dict):
        async with send_lock:
            await websocket.send_json(payload)

    async def _correct_in_background(seg, prev_texts):
        """저신뢰 세그먼트를 비동기 보정 후 corrected 메시지 전송(수신 루프 비차단)."""
        try:
            corrected_text = await LLMCorrector.get_instance().correct_async(seg.text, prev_texts)
            if corrected_text and corrected_text != seg.text:
                seg.original_text = seg.text
                seg.text = corrected_text
                seg.corrected = True
                await _ws_send({
                    "type": "corrected", "session_id": session_id,
                    "segment_id": seg.id, "text": corrected_text,
                })
                logger.info(f"✏️ Sent corrected: {corrected_text[:50]}")
        except Exception as e:
            logger.warning(f"⚠️ 백그라운드 보정 실패(원문 유지): {e}")

    # ── 지연(deferred) 보정: 대기 큐 + 주기 스윕 워커 ──
    # 저신뢰 세그먼트를 즉시 보정하지 않고 큐에 적재 → 확정 후 LLM_DEFER_SECONDS(기본 30s)
    # 경과분만 모아 후속 처리. STT 자막은 지연 없이 즉시 표시되고 GPU 경쟁 스파이크도 분산.
    pending_corrections: list = []  # [{"seg":.., "prev_texts":.., "ts":..}]

    async def _correction_worker():
        try:
            while True:
                await asyncio.sleep(settings.LLM_SWEEP_INTERVAL)
                if not pending_corrections:
                    continue
                now = time.monotonic()
                due = [p for p in pending_corrections
                       if now - p["ts"] >= settings.LLM_DEFER_SECONDS][:settings.LLM_BATCH_SIZE]
                for p in due:
                    try:
                        pending_corrections.remove(p)
                    except ValueError:
                        continue
                    await _correct_in_background(p["seg"], p["prev_texts"])
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"⚠️ 보정 워커 오류: {e}")

    async def _flush_pending_corrections():
        """종료 시: 지연 무시하고 남은 대기분 전량 보정(최종 저장 반영)."""
        items = list(pending_corrections)
        pending_corrections.clear()
        if items:
            logger.info(f"🧹 종료 flush: 대기 보정 {len(items)}건 처리")
        for p in items:
            await _correct_in_background(p["seg"], p["prev_texts"])

    correction_worker_task = None
    if settings.LLM_CORRECTION_MODE == "deferred":
        correction_worker_task = asyncio.create_task(_correction_worker())
        logger.info(f"🕒 지연 보정 모드: {settings.LLM_DEFER_SECONDS:.0f}초 후속 배치")

    # Tier 3: 회의 시작~종료 전체 오디오를 디스크에 누적 보존 (화자분리/보관용)
    os.makedirs(str(settings.AUDIO_DIR), exist_ok=True)
    session_audio_path = os.path.join(str(settings.AUDIO_DIR), f"{session_id}.f32")
    if resumed:
        # 이어쓰기: 기존 오디오 파일 유지하고, 그 길이만큼 전역 오프셋 복원(타임라인 연속)
        if os.path.exists(session_audio_path):
            global_offset_sec = os.path.getsize(session_audio_path) / 4 / 16000
        elif finalized_segments:
            global_offset_sec = max((s.end for s in finalized_segments), default=0.0)
        logger.info(f"♻️ 이어쓰기 오프셋 복원: {global_offset_sec:.1f}s")
    else:
        # 신규: 잔여 파일 제거
        try:
            if os.path.exists(session_audio_path):
                os.remove(session_audio_path)
        except OSError:
            pass

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

                # Tier 3: 회의 전체 오디오를 디스크에 누적(모든 청크, VAD 무관) → 종료 시 화자분리/보관
                try:
                    with open(session_audio_path, "ab") as af:
                        af.write(raw_bytes)
                except Exception as audio_err:
                    logger.error(f"세션 오디오 누적 저장 실패: {audio_err}")

                # 세션 길이 상한 가드(폭주/누수 방지)
                try:
                    session_sec = os.path.getsize(session_audio_path) / 4 / 16000
                    if session_sec > settings.MAX_SESSION_DURATION_SEC:
                        logger.warning(f"⏹️ 세션 길이 상한 도달({session_sec:.0f}s) → 종료 처리")
                        await websocket.send_json({
                            "type": "info", "session_id": session_id,
                            "message": "최대 회의 길이에 도달하여 자동 종료합니다."
                        })
                        break
                except OSError:
                    pass

                # VAD 트리거로만 임시 전사 실행 (이미 2초 무음 대기로 최적화됨)
                # 일정 간격 트리거는 제거하여 불필요한 공백 처리 방지
                if vad_triggered:
                    # Tier 3: 최소 청크 길이 가드 - 너무 짧은 버퍼는 전사 스킵(노이즈/환각 방지)
                    # clear하지 않고 누적시켜 다음 트리거에 합산 → 짧은 발화 유실 방지
                    buffered_sec = len(audio_processor.get_audio_data()) / 16000
                    if buffered_sec < settings.MIN_CHUNK_DURATION_SEC:
                        logger.debug(
                            f"⏭️ 짧은 버퍼 전사 스킵(누적 유지): {buffered_sec:.2f}s < "
                            f"{settings.MIN_CHUNK_DURATION_SEC}s"
                        )
                        continue

                    # 1. 임시 WAV 파일 생성 (Whisper 추론용)
                    import time
                    start_time = time.time()
                    # Tier 2: 이번 버퍼의 회의 내 시작 시각(오프셋)과 길이 기록
                    offset_before = global_offset_sec
                    processed_samples = len(audio_processor.get_audio_data())
                    temp_wav = save_audio_buffer_to_file(audio_processor.get_audio_data())

                    try:
                        # 2. Whisper 전사 수행 (실시간 처리: beam_size=1, 자동 언어 감지 + ko 폴백)
                        # ThreadPoolExecutor에 의해 GPU 추론 직렬화 보장
                        # Tier 3: 실시간에서는 initial_prompt를 끄는 것이 기본(짧은 청크 환각 방지)
                        whisper_start = time.time()
                        realtime_prompt = (
                            settings.CONTEXT_PROMPTS.get("bilingual", "")
                            if settings.REALTIME_USE_INITIAL_PROMPT else ""
                        )
                        whisper_results = await asyncio.get_event_loop().run_in_executor(
                            stt_engine.executor,
                            stt_engine._transcribe_sync,  # 동기 래퍼 직접 사용
                            temp_wav,
                            None,                         # ← 자동 언어 감지 + 저신뢰 시 ko 폴백
                            settings.BEAM_SIZE_FAST,      # ⭐ 실시간 처리: 빠른 응답
                            realtime_prompt               # Tier 3: 기본 "" (프롬프트 비활성)
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

                                seg_id = f"rt-{session_id}-{conn_nonce}-{processing_count}-{idx}"
                                try:
                                    # 임시: 화자 분리는 나중에 수행하므로 기본값으로 설정
                                    trans_segment = TranscriptSegment(
                                        id=seg_id,
                                        session_id=session_id,
                                        # Tier 2: 청크 로컬 타임스탬프에 회의 전역 오프셋을 더해 연속 타임라인 구성
                                        start=round(float(raw_seg.get("start", 0)) + offset_before, 2),
                                        end=round(float(raw_seg.get("end", 0)) + offset_before, 2),
                                        text=str(raw_seg.get("text", "")).strip(),
                                        speaker="SPEAKER_00",
                                        confidence=float(raw_seg.get("confidence", 0)),
                                        is_final=True
                                    )

                                    await _ws_send({
                                        "type": "final",
                                        "session_id": session_id,
                                        "segment": trans_segment.dict(),
                                        "gpu_usage_mb": vram_used
                                    })
                                    logger.info(f"✅ Sent final: {trans_segment.text[:50]}")

                                    # 중복 확인 후 저장
                                    if seg_id not in [s.id for s in finalized_segments]:
                                        prev_texts = [s.text for s in finalized_segments[-3:]]  # 직전 문맥(현재 추가 전)
                                        finalized_segments.append(trans_segment)
                                        session_manager.add_segment(session_id, trans_segment)
                                        segment_count += 1

                                        # LLM 문맥 보정 (저신뢰 + 교정가치 있는 세그먼트만).
                                        # deferred(기본): 즉시 보정하지 않고 대기 큐에 적재 → 30초 후속 배치.
                                        # realtime: 즉시 백그라운드 보정. off: 보정 안 함.
                                        # trans_segment는 세션에 참조 저장되므로 보정 시 최종 결과에도 반영됨.
                                        corrector = LLMCorrector.get_instance()
                                        if corrector.should_correct(trans_segment.confidence, trans_segment.text):
                                            if settings.LLM_CORRECTION_MODE == "deferred":
                                                pending_corrections.append({
                                                    "seg": trans_segment,
                                                    "prev_texts": prev_texts,
                                                    "ts": time.monotonic(),
                                                })
                                            elif settings.LLM_CORRECTION_MODE == "realtime":
                                                task = asyncio.create_task(
                                                    _correct_in_background(trans_segment, prev_texts)
                                                )
                                                correction_tasks.add(task)
                                                task.add_done_callback(correction_tasks.discard)
                                            # "off": 보정 생략
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

                        # Tier 2: 처리한 버퍼 길이만큼 회의 전역 오프셋 전진
                        global_offset_sec += processed_samples / 16000

                        # Whisper 처리 완료 후 버퍼 초기화 (중복 처리 방지)
                        # (전체 오디오는 session_audio_path에 별도 누적되므로 여기서 버려도 안전)
                        audio_processor.clear()
                        logger.debug(f"🗑️ Audio buffer cleared (global_offset={global_offset_sec:.2f}s)")

                    finally:
                        if os.path.exists(temp_wav):
                            os.remove(temp_wav)
                            
            elif "text" in message:
                # 텍스트 명령 수신 처리 (예: 녹음 강제 정지 등 제어)
                import json
                data = json.loads(message["text"])
                if data.get("command") == "stop":
                    logger.info("Client requested stream stop. (명시적 회의 종료 → 최종 후처리)")
                    finalize_requested = True
                    break
                    
    except WebSocketDisconnect:
        logger.info(f"WebSocket session {session_id} disconnected by client.")
    except Exception as e:
        # 끊김/수신 오류를 failed로 마킹하지 않음 → 재연결 이어쓰기 가능(processing 유지).
        # 영영 안 돌아오는 세션은 고아 GC가 마감. 누적 세그먼트는 이미 영속됨.
        logger.error(f"Error in WebSocket streaming loop (세션 유지, 재연결 가능): {e}")
        try:
            await websocket.send_json({"type": "error", "session_id": session_id, "error": str(e)})
        except Exception:
            pass
        
    # 활성 세션 해제 (재연결이 같은 id로 다시 들어올 수 있도록 항상 먼저 해제)
    _active_ws_sessions.discard(session_id)

    # 지연 보정 워커 정지 (항상)
    if correction_worker_task:
        correction_worker_task.cancel()
        try:
            await correction_worker_task
        except (asyncio.CancelledError, Exception):
            pass

    # ★ 종료 트리거 구분: 명시적 'stop'일 때만 최종 후처리. 단순 끊김은 이어쓰기 대기.
    if not finalize_requested:
        # 단순 끊김: 미보정 대기분은 폐기(재연결/재처리 단순화), 누적 세그먼트는 이미 영속됨.
        logger.info(
            f"⏸️ 연결 끊김(재연결 대기) → 종료 후처리 생략, 세션 유지(processing): {session_id} "
            f"({len(finalized_segments)} segments 보존, 대기 보정 {len(pending_corrections)}건 폐기)"
        )
        return

    # 명시적 종료: 남은 대기 보정 전량 flush + 진행중 태스크 완료 대기 → 최종 저장에 반영
    await _flush_pending_corrections()
    if correction_tasks:
        logger.info(f"⏳ 보정 태스크 {len(correction_tasks)}건 완료 대기...")
        await asyncio.gather(*list(correction_tasks), return_exceptions=True)

    # ==========================================================
    # 명시적 회의 종료(stop) 시 최종 후처리 (Tier 1+3)
    #  - 핵심 원칙: 실시간 누적 세그먼트(finalized_segments=전체 회의록)를
    #    절대 비우거나 마지막 청크로 교체하지 않는다.
    #  - 보존된 전체 오디오(session_audio_path)로 화자분리를 1회 수행하여
    #    누적 세그먼트에 speaker 라벨만 매핑한다(텍스트/타임라인 보존).
    # ==========================================================
    logger.info(f"🔄 Final post-processing for session: {session_id} ({len(finalized_segments)} accumulated segments)")

    # 전체 회의 오디오 로드 (스트리밍 중 디스크에 누적된 f32)
    full_audio = None
    try:
        if os.path.exists(session_audio_path) and os.path.getsize(session_audio_path) > 0:
            full_audio = np.fromfile(session_audio_path, dtype=np.float32)
    except Exception as load_err:
        logger.error(f"❌ Failed to load session audio: {load_err}")
        full_audio = None

    base_segments = finalized_segments  # ★ 항상 전체 누적이 기준 (절대 교체/삭제 금지)
    min_audio_samples = 16000  # 최소 1초

    temp_full_wav = None
    try:
        # duration: 보존된 전체 오디오 기준 (없으면 마지막 세그먼트 end로 폴백)
        actual_duration = 0.0
        if full_audio is not None and len(full_audio) > 0:
            temp_full_wav = save_audio_buffer_to_file(full_audio)
            actual_duration = get_audio_duration(temp_full_wav)
            if actual_duration <= 0:
                actual_duration = round(len(full_audio) / 16000, 2)
        elif base_segments:
            actual_duration = max((s.end for s in base_segments), default=0.0)
        logger.info(f"✅ 전체 회의 길이: {actual_duration:.2f}s, 누적 세그먼트 {len(base_segments)}개")

        # 전체 오디오로 화자분리 1회 → 누적 세그먼트에 speaker만 매핑 (텍스트 보존)
        if full_audio is not None and len(full_audio) >= min_audio_samples and base_segments:
            try:
                diarization_results = await diarizer.diarize(temp_full_wav)
                if diarization_results:
                    base_segments = assign_speakers(base_segments, diarization_results)
                    logger.info(f"🗣️ 화자 매핑 완료: {len(diarization_results)} turns")
                else:
                    logger.warning("⚠️ 화자분리 결과 없음 → 기존 화자 라벨 유지")
            except Exception as diar_err:
                logger.error(f"❌ Diarization failed (누적 세그먼트는 보존): {diar_err}")
        else:
            logger.info("ℹ️ 오디오가 짧거나 없음 → 화자분리 생략, 누적 세그먼트 그대로 완료")

        # 세션 완료 (누적 세그먼트를 그대로 저장 — 절대 [] 또는 마지막 청크로 교체하지 않음)
        unique_speakers = {seg.speaker for seg in base_segments if seg.speaker}
        session_manager.update_session(
            session_id,
            status="completed",
            duration_sec=round(actual_duration, 2),
            speaker_count=len(unique_speakers),
            segments=base_segments,
            audio_path=session_audio_path if (full_audio is not None and len(full_audio) > 0) else None,
        )
        logger.info(f"✅ Session {session_id} completed: {len(base_segments)} segments, {len(unique_speakers)} speakers")

        # 클라이언트에 최종(화자 반영) 결과 전송
        if base_segments:
            try:
                await _ws_send({
                    "type": "speaker_updated",
                    "session_id": session_id,
                    "message": "Final diarization complete.",
                    "segments": [seg.dict() for seg in base_segments],
                })
                logger.info(f"📤 Sent speaker_updated message to client")
            except Exception as send_err:
                logger.debug(f"ℹ️ Client connection closed before final message: {send_err}")

    except Exception as ex:
        # 후처리 실패해도 누적 세그먼트는 보존 (status만 completed로, 데이터 손실 방지)
        logger.error(f"❌ Post-processing failed (누적 세그먼트 보존): {ex}", exc_info=True)
        session_manager.update_session(
            session_id,
            status="completed",
            duration_sec=round(max((s.end for s in base_segments), default=0.0), 2),
            speaker_count=len({s.speaker for s in base_segments if s.speaker}),
            segments=base_segments,
        )
    finally:
        if temp_full_wav and os.path.exists(temp_full_wav):
            try:
                os.remove(temp_full_wav)
            except OSError as cleanup_err:
                logger.error(f"Failed to remove temp file: {cleanup_err}")
