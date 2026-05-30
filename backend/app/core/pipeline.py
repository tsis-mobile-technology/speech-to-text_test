import os
import uuid
import logging
from app.core.stt_engine import STTEngine
from app.core.diarization import DiarizationEngine
from app.core.llm_corrector import LLMCorrector
from app.utils.audio import convert_to_wav_16k_mono, get_audio_duration
from app.models.transcript import TranscriptSegment

logger = logging.getLogger(__name__)


def assign_speakers(segments: list[TranscriptSegment], diarization_segments: list[dict]) -> list[TranscriptSegment]:
    """
    이미 누적된 세그먼트(전역 타임스탬프)에 화자 라벨만 매핑한다.
    텍스트/시간은 보존하고 speaker 필드만 갱신 → 전체 회의록을 잃지 않음.
    매칭: 중심점(midpoint) 우선, 실패 시 최대 오버랩.
    """
    if not diarization_segments:
        return segments

    for seg in segments:
        mid = (seg.start + seg.end) / 2
        speaker = None
        for d in diarization_segments:
            if d["start"] <= mid <= d["end"]:
                speaker = d["speaker"]
                break
        if speaker is None:
            max_overlap = 0.0
            best = seg.speaker or "SPEAKER_00"
            for d in diarization_segments:
                overlap = max(0.0, min(seg.end, d["end"]) - max(seg.start, d["start"]))
                if overlap > max_overlap:
                    max_overlap = overlap
                    best = d["speaker"]
            speaker = best
        seg.speaker = speaker
    return segments


async def apply_llm_correction(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """
    저신뢰 세그먼트에 한해 LLM 문맥 보정을 적용한다(설정에 따라).
    직전 N개 문장(보정된 텍스트 우선)을 문맥으로 전달. 실패 시 원문 유지.
    """
    corrector = LLMCorrector.get_instance()
    if not corrector.is_enabled():
        return segments

    corrected_count = 0
    for i, seg in enumerate(segments):
        if not corrector.should_correct(seg.confidence, seg.text):
            continue
        prev_texts = [s.text for s in segments[max(0, i - 3):i]]  # 직전 최대 3개
        new_text = await corrector.correct_async(seg.text, prev_texts)
        if new_text and new_text != seg.text:
            seg.original_text = seg.text
            seg.text = new_text
            seg.corrected = True
            corrected_count += 1

    if corrected_count > 0:
        logger.info(f"✏️ LLM 후교정 적용: {corrected_count}개 세그먼트 (저신뢰)")
    return segments

def align_segments(whisper_segments: list[dict], diarization_segments: list[dict], session_id: str, detected_language: str = "unknown") -> list[TranscriptSegment]:
    """
    Whisper 자막 구간과 Pyannote 화자 세그먼트를 시간 오버랩 기준으로 병합 정렬합니다.
    """
    aligned = []
    
    for i, w_seg in enumerate(whisper_segments):
        w_start = w_seg["start"]
        w_end = w_seg["end"]
        w_mid = (w_start + w_end) / 2
        
        # 1차 매칭: Whisper 세그먼트의 중심점(Midpoint)이 Pyannote 화자 구간 내에 존재하는지 탐색
        speaker = None
        for d_seg in diarization_segments:
            if d_seg["start"] <= w_mid <= d_seg["end"]:
                speaker = d_seg["speaker"]
                break
                
        # 2차 매칭: 중심점 매칭이 실패한 경우, 오버랩 시간(Overlap duration)이 가장 높은 화자 선택
        if speaker is None:
            max_overlap = 0.0
            best_speaker = "SPEAKER_00"  # 기본값
            
            for d_seg in diarization_segments:
                # 겹치는 구간 계산
                overlap_start = max(w_start, d_seg["start"])
                overlap_end = min(w_end, d_seg["end"])
                overlap = max(0.0, overlap_end - overlap_start)
                
                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = d_seg["speaker"]
            
            speaker = best_speaker
            
        # Pydantic 모델로 자막 세그먼트 인스턴스 생성
        segment_language = w_seg.get("language", detected_language)  # 세그먼트별 언어 또는 전체 감지 언어
        no_speech_prob = w_seg.get("no_speech_prob")  # Hallucination 감지용
        aligned.append(
            TranscriptSegment(
                id=str(uuid.uuid4()),
                session_id=session_id,
                start=w_start,
                end=w_end,
                text=w_seg["text"],
                speaker=speaker,
                confidence=w_seg["confidence"],
                is_final=True,
                detected_language=segment_language,
                no_speech_prob=no_speech_prob
            )
        )
        
    return aligned

async def run_stt_diarization_pipeline(session_id: str, file_path: str, enable_diarization: bool = True,
                                       beam_size: int = None, context: str = "meeting") -> tuple[list[TranscriptSegment], float, int]:
    """
    오디오 파일에 대해 전처리 -> STT -> 화자분리 -> 타임스탬프 정렬 파이프라인을 실행합니다.

    Args:
        session_id: 세션 ID
        file_path: 오디오 파일 경로
        enable_diarization: 화자분리 활성화 여부 (기본값: True)
        beam_size: 빔 검색 크기 (None=balanced 사용)
        context: 도메인 문맥 ("meeting", "technical", "general")
    """
    logger.info(f"Starting pipeline for session: {session_id}, file: {file_path}, beam_size={beam_size}, context={context}")

    # 1. 오디오 리샘플링 (16kHz mono WAV 변환)
    processed_path = file_path
    is_temp = False
    try:
        converted = convert_to_wav_16k_mono(file_path)
        if converted != file_path:
            processed_path = converted
            is_temp = True
    except Exception as e:
        logger.warning(f"Audio preprocessing failed: {e}. Attempting direct processing.")

    duration = get_audio_duration(processed_path)

    try:
        # 2. STT (faster-whisper) 추론 실행 (파일용: beam_size=3 권장)
        # stt_engine의 ThreadPoolExecutor를 타기 때문에 비동기적으로 스레드가 직렬 처리됨
        stt_engine = STTEngine.get_instance()
        from app.config import settings
        if beam_size is None:
            beam_size = settings.BEAM_SIZE_BALANCED
        initial_prompt = settings.CONTEXT_PROMPTS.get(context, "")

        # 파일 업로드: 자동 언어 감지 사용 (language=None)
        # → 영어-한국어 혼합 음성 정확도 향상
        whisper_results = await stt_engine.transcribe(processed_path, language=None, beam_size=beam_size,
                                                     initial_prompt=initial_prompt)
        
        diarization_results = []
        unique_speakers = {"SPEAKER_00"}
        
        # 3. 화자분리 (pyannote.audio) 실행 (옵션에 따라 건너뛰기 가능)
        if enable_diarization and duration > 0.5:
            diarizer = DiarizationEngine.get_instance()
            # diarize 역시 ThreadPoolExecutor 내부에서 순차 실행됨
            diarization_results = await diarizer.diarize(processed_path)
            
            if diarization_results:
                unique_speakers = {seg["speaker"] for seg in diarization_results}
        
        # 4. 시간 정렬(Alignment) 후처리
        # 첫 번째 세그먼트에서 감지된 언어 추출
        detected_lang = whisper_results[0].get("language", "unknown") if whisper_results else "unknown"
        final_segments = align_segments(whisper_results, diarization_results, session_id, detected_language=detected_lang)

        # 5. LLM 문맥 후교정 (저신뢰 세그먼트 한정, 설정 시)
        final_segments = await apply_llm_correction(final_segments)

        logger.info(f"✅ 파이프라인 완료: 세그먼트 {len(final_segments)}개, 화자 {len(unique_speakers)}명, 언어 {detected_lang}")
        return final_segments, duration, len(unique_speakers)
        
    finally:
        # 생성된 임시 리샘플링 파일 삭제하여 디스크 누수 방지
        if is_temp and os.path.exists(processed_path):
            try:
                os.remove(processed_path)
                logger.info(f"Cleaned up temporary audio file: {processed_path}")
            except OSError as e:
                logger.error(f"Failed to remove temporary file {processed_path}: {e}")
