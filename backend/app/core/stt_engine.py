import os
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from app.config import settings

logger = logging.getLogger(__name__)

# faster-whisper가 로드 가능할 때만 임포트
try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    logger.warning("faster-whisper is not installed. Running STT in mock mode.")
    WHISPER_AVAILABLE = False

def _is_repetitive_text(text: str) -> bool:
    """
    문자/n-gram 단위 반복 할루시네이션을 탐지한다 (콤마 기반 필터의 사각지대 보완).
    예: 'ㄷㄷㄷㄷ', 'ㅋㅋㅋㅋ', '네네네네', '그래그래그래' 등 콤마 없는 반복.
    임계값은 config.py에서 '균형' 수준으로 노출되어 튜닝 가능.
    """
    t = text.strip().replace(" ", "")
    if len(t) < settings.REPETITION_MIN_LENGTH:
        return False  # 짧은 정상 발화 보호

    # 1) 단일 문자 점유율 (ㄷㄷㄷ, ㅋㅋㅋ)
    most_common_ratio = max(t.count(c) for c in set(t)) / len(t)
    if most_common_ratio > settings.CHAR_REPETITION_RATIO:
        return True

    # 2) 고유 문자 다양성 (글자 종류가 극도로 적음)
    if len(set(t)) / len(t) < settings.CHAR_DIVERSITY_MIN:
        return True

    # 3) 2~4-gram 반복 (그래그래그래, 네네네네)
    for n in (2, 3, 4):
        grams = [t[i:i + n] for i in range(0, len(t) - n + 1, n)]
        if len(grams) >= 3 and len(set(grams)) / len(grams) < settings.NGRAM_REPETITION_RATIO:
            return True

    return False


def _is_jamo_char(c: str) -> bool:
    """완성되지 않은 한글 자모(ㄱ,ㄷ,ㄳ,ㅏ 등) 여부. (완성형 음절 가-힣은 제외)"""
    o = ord(c)
    return 0x3130 <= o <= 0x318F or 0x1100 <= o <= 0x11FF


def _is_garbage_korean(text: str) -> bool:
    """
    자모-only / 깨진 한글 텍스트(환각·노이즈) 탐지.
    - 완성형 음절(가-힣)도 영숫자도 없고 자모만 있으면 garbage (예: 'ㄷㄷ', 'ㄱㄷ', 'ㄴㄴㅇㄴ').
    - 자모 비율이 임계 이상이면 깨진 텍스트로 간주.
    정상 한국어('안녕하세요')·영어는 통과. 길이와 무관하게 단일 자모 garbage를 잡는다.
    """
    t = "".join(text.split())
    if not t:
        return True
    has_syllable = any("가" <= c <= "힣" for c in t)  # 완성형 한글
    has_ascii_alnum = any(c.isascii() and c.isalnum() for c in t)  # 영문/숫자
    jamo_count = sum(1 for c in t if _is_jamo_char(c))

    if not has_syllable and not has_ascii_alnum and jamo_count > 0:
        return True  # 완성형/영숫자 전무 + 자모만 → garbage
    if jamo_count / len(t) > settings.JAMO_RATIO_THRESHOLD:
        return True  # 자모 비율 과다 → 깨진 텍스트
    return False


class STTEngine:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
        
    def __init__(self):
        # max_workers=1로 설정하여 다수의 요청이 동시 처리되는 것을 방지하고 GPU 추론을 직렬화(큐잉)합니다.
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.model = None
        
    def load_model(self):
        """
        Whisper 모델을 메모리(VRAM)에 1회만 로드합니다.
        """
        if self.model is not None:
            return
            
        if not WHISPER_AVAILABLE:
            logger.warning("Mocking Whisper Model initialization...")
            return

        model_path = str(settings.WHISPER_MODEL_PATH)
        # 로컬 사전 다운로드 경로가 없는 경우, Hugging Face ID로 다운로드 시도
        if not settings.WHISPER_MODEL_PATH.exists():
            logger.info(f"Local model not found at {settings.WHISPER_MODEL_PATH}. Fetching from HF Hub using: {settings.WHISPER_MODEL_SIZE}")
            model_path = settings.WHISPER_MODEL_SIZE
            
        logger.info(f"Loading Whisper model from: {model_path} (Device: {settings.WHISPER_DEVICE}, Compute Type: {settings.WHISPER_COMPUTE_TYPE})...")
        try:
            self.model = WhisperModel(
                model_size_or_path=model_path,
                device=settings.WHISPER_DEVICE,
                compute_type=settings.WHISPER_COMPUTE_TYPE
            )
            logger.info("Whisper model loaded successfully into GPU memory.")
        except Exception as e:
            logger.error(f"Failed to load Whisper model to GPU. Attempting cpu fallback: {e}")
            self.model = WhisperModel(
                model_size_or_path=settings.WHISPER_MODEL_SIZE,
                device="cpu",
                compute_type="float32"
            )
            logger.info("Whisper model loaded on CPU.")

    async def transcribe(self, audio_path: str, language: str = None, beam_size: int = None,
                        initial_prompt: str = None) -> list[dict]:
        """
        비동기 이벤트 루프를 블로킹하지 않기 위해 ThreadPoolExecutor에서 Whisper 추론을 수행합니다.

        Args:
            audio_path: 음성 파일 경로
            language: 언어 코드 (기본값: None=자동 감지)
                - None: 자동 감지 (권장)
                - "ko": 한국어 강제
                - "en": 영어 강제
            beam_size: 빔 검색 크기 (None=balanced 사용)
            initial_prompt: 초기 프롬프트 (문맥 정보)
        """
        if beam_size is None:
            beam_size = settings.BEAM_SIZE_BALANCED

        return await asyncio.get_event_loop().run_in_executor(
            self.executor,
            self._transcribe_sync,
            audio_path,
            language,
            beam_size,
            initial_prompt
        )

    def _transcribe_sync(self, audio_path: str, language: str, beam_size: int, initial_prompt: str = None) -> list[dict]:
        self.load_model()

        if not WHISPER_AVAILABLE or self.model is None:
            # Mock 모드: 가짜 데이터 반환 (음성 파일 길이 기반 모의 세그먼트 생성)
            logger.warning("Whisper mock inference triggered.")
            import time
            time.sleep(2.0)  # 연산 모사
            return [
                {"start": 0.5, "end": 3.0, "text": "[Mock] 안녕하세요, 본 메시지는 STT 엔진이 모의로 작동 중일 때 출력됩니다.", "confidence": 0.95, "language": "ko"},
                {"start": 3.5, "end": 7.0, "text": "[Mock] 로컬 머신에 PyTorch 및 CUDA, faster-whisper가 올바르게 셋업되었는지 확인해 주세요.", "confidence": 0.92, "language": "ko"}
            ]

        try:
            # 언어 설정: None이면 자동 감지, 그 외에는 사용자가 지정한 언어 사용
            # 자동 감지 권장 (설정에서 제어 가능)
            if language is None and settings.AUTO_DETECT_LANGUAGE:
                # None으로 설정 → Whisper 자동 감지
                whisper_language = None
                logger.info(f"🌐 언어 자동 감지 활성화")
            else:
                whisper_language = language if language else None
                if language:
                    logger.info(f"🔒 언어 강제 설정: {language}")

            # 초기 프롬프트가 없으면 도메인별 기본값 사용 (회의 대화)
            # 다국어 혼합 오디오는 bilingual 프롬프트 사용 권장
            # (실시간 경로는 websocket에서 ""을 넘겨 프롬프트를 끌 수 있음 → Tier 3)
            if initial_prompt is None:
                # 자동 감지 시 bilingual 프롬프트 사용 (영어-한국어 혼합 대비)
                domain = "bilingual" if settings.AUTO_DETECT_LANGUAGE and language is None else "meeting"
                initial_prompt = settings.CONTEXT_PROMPTS.get(domain, "")
                logger.info(f"📝 Context Prompt 적용: {domain}")

            def _run_transcribe(lang):
                # info(언어 감지 결과)는 segments 제너레이터 소비 전에 이미 계산되므로,
                # 폴백 전 첫 호출은 전체 디코딩 비용 없이 언어 감지만 수행된다.
                return self.model.transcribe(
                    audio_path,
                    language=lang,  # None으로 설정하면 자동 감지
                    beam_size=beam_size,
                    temperature=settings.TEMPERATURE,
                    initial_prompt=initial_prompt,
                    vad_filter=settings.VAD_FILTER_ENABLED,  # ⭐ VAD 활성화 (무음/노이즈 제거)
                    vad_parameters={"min_silence_duration_ms": settings.VAD_MIN_SILENCE_DURATION_MS},
                    # ── Tier 1: 디코딩 단계 할루시네이션 억제 (반복을 생성 시점에 차단) ──
                    condition_on_previous_text=settings.CONDITION_ON_PREVIOUS_TEXT,
                    no_repeat_ngram_size=settings.NO_REPEAT_NGRAM_SIZE,
                    repetition_penalty=settings.REPETITION_PENALTY,
                    compression_ratio_threshold=settings.WHISPER_COMPRESSION_RATIO_THRESHOLD,
                    log_prob_threshold=settings.WHISPER_LOG_PROB_THRESHOLD,
                    no_speech_threshold=settings.WHISPER_NO_SPEECH_THRESHOLD,
                    hallucination_silence_threshold=settings.HALLUCINATION_SILENCE_THRESHOLD,
                )

            segments, info = _run_transcribe(whisper_language)

            # ── Tier 3: 언어 감지 폴백 ──
            # 자동 감지인데 감지 확률이 낮으면(불안정) 한국어로 강제 재전사하여 할루시네이션 방지.
            # 예: 'ko' @ 0.52처럼 모델이 확신 못 하는 구간이 반복/잡음 환각을 유발했음.
            if whisper_language is None and settings.AUTO_DETECT_LANGUAGE:
                lang_prob = getattr(info, 'language_probability', 1.0)
                detected = getattr(info, 'language', None)
                if lang_prob < settings.LANGUAGE_FALLBACK_THRESHOLD:
                    logger.warning(
                        f"⚠️ 언어 감지 불안정 ({detected} @ {lang_prob:.2f} < "
                        f"{settings.LANGUAGE_FALLBACK_THRESHOLD}) → '{settings.FALLBACK_LANGUAGE}' 강제 재전사"
                    )
                    segments, info = _run_transcribe(settings.FALLBACK_LANGUAGE)

            # 감지된 언어 로깅
            detected_language = getattr(info, 'language', 'unknown')
            lang_prob_final = getattr(info, 'language_probability', None)
            logger.info(
                f"✅ 감지된 언어: {detected_language}"
                + (f" (prob={lang_prob_final:.2f})" if lang_prob_final is not None else "")
            )

            result = []
            filtered_count = 0  # 필터링된 세그먼트 수

            for segment in segments:
                # logprob를 신뢰도(confidence) 백분율로 모사 변환 (exp(logprob) 형태로 근사치 계산)
                import math
                conf = round(math.exp(max(segment.avg_logprob, -5.0)), 2)

                # Hallucination 필터링 0: 로그확률 기반 필터 (평균 로그확률이 극도로 낮음)
                if segment.avg_logprob < settings.LOG_PROB_THRESHOLD:
                    logger.warning(
                        f"🚫 로그확률 기반 필터링 (신뢰도 극도 부족): "
                        f"{segment.avg_logprob:.3f} < {settings.LOG_PROB_THRESHOLD} - '{segment.text[:50]}'"
                    )
                    filtered_count += 1
                    continue

                # Hallucination 필터링 1: 신뢰도 임계값
                if conf < settings.CONFIDENCE_THRESHOLD:
                    logger.warning(
                        f"🚫 낮은 신뢰도로 필터링 (Hallucination 가능): "
                        f"{conf:.2%} < {settings.CONFIDENCE_THRESHOLD} - '{segment.text[:50]}'"
                    )
                    filtered_count += 1
                    continue

                # Hallucination 필터링 2: 최소 세그먼트 길이
                segment_duration = segment.end - segment.start
                if segment_duration < settings.MIN_SEGMENT_LENGTH:
                    logger.warning(
                        f"🚫 너무 짧은 세그먼트 필터링 (노이즈): "
                        f"{segment_duration:.2f}s < {settings.MIN_SEGMENT_LENGTH}s - '{segment.text[:30]}'"
                    )
                    filtered_count += 1
                    continue

                # Hallucination 필터링 3: no_speech_prob (음성이 없을 확률)
                no_speech_prob = getattr(segment, 'no_speech_prob', None)
                if no_speech_prob is not None and no_speech_prob > settings.NO_SPEECH_THRESHOLD:
                    logger.warning(
                        f"🚫 음성 없음 확률로 필터링: "
                        f"{no_speech_prob:.2%} > {settings.NO_SPEECH_THRESHOLD:.0%} - '{segment.text[:50]}'"
                    )
                    filtered_count += 1
                    continue

                # Hallucination 필터링 3.5: 압축률 기반 필터 (짧은 음성에 긴 텍스트 = 반복 의심)
                segment_duration = segment.end - segment.start
                compression_ratio = len(segment.text) / max(segment_duration, 0.1)
                if compression_ratio > settings.COMPRESSION_RATIO_THRESHOLD:
                    logger.warning(
                        f"🚫 압축률 기반 필터링 (반복 의심): "
                        f"{compression_ratio:.2f} > {settings.COMPRESSION_RATIO_THRESHOLD} - '{segment.text[:50]}'"
                    )
                    filtered_count += 1
                    continue

                # 검증 통과: 세그먼트 추가
                result.append({
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": segment.text.strip(),
                    "confidence": conf,
                    "language": detected_language,  # 감지된 언어
                    "no_speech_prob": round(no_speech_prob, 3) if no_speech_prob else None  # 음성 없을 확률
                })

            if filtered_count > 0:
                logger.info(f"✅ 총 {filtered_count}개 Hallucination 세그먼트 필터링됨")

            # 최종 검증: 반복 텍스트 감지 (hallucination 최종 방어선)
            final_result = []
            for seg in result:
                text = seg["text"].strip()

                # Hallucination 최종 방어 -1: 자모-only/깨진 한글 (ㄷㄷ, ㄱㄷ, ㄴㄴㅇㄴ 등, 길이 무관)
                if settings.FILTER_JAMO_ONLY and _is_garbage_korean(text):
                    logger.warning(f"🚫 자모-only/깨진 텍스트 필터링 (Hallucination): '{text[:50]}'")
                    filtered_count += 1
                    continue

                # Hallucination 최종 방어 0 (Tier 2): 문자/n-gram 단위 반복 감지
                # 예: "ㄷㄷㄷㄷ", "ㅋㅋㅋ", "네네네네" (콤마 없는 반복 → 아래 콤마 필터의 사각지대)
                if _is_repetitive_text(text):
                    logger.warning(
                        f"🚫 문자/n-gram 반복으로 필터링 (Hallucination): '{text[:50]}'"
                    )
                    filtered_count += 1
                    continue

                # Hallucination 최종 방어: 반복 단어 감지
                # 예: "안녕하세요, 안녕하세요, 안녕하세요"
                words = text.split(',')
                if len(words) > 3:
                    # 반복 패턴 확인
                    unique_words = set(w.strip() for w in words if w.strip())
                    repeat_ratio = 1 - (len(unique_words) / len(words))

                    if repeat_ratio > settings.REPETITION_THRESHOLD:
                        logger.warning(
                            f"🚫 반복 텍스트로 필터링 (Hallucination): "
                            f"{repeat_ratio:.0%} > {settings.REPETITION_THRESHOLD:.0%} 반복 - '{text[:50]}'"
                        )
                        filtered_count += 1
                        continue

                final_result.append(seg)

            if filtered_count > 0:
                logger.info(f"✅ 총 {filtered_count}개 Hallucination 세그먼트 필터링됨 (반복 텍스트 포함)")

            return final_result
        except Exception as e:
            logger.error(f"Error during Whisper transcription: {e}")
            raise e

    def release(self):
        """
        GPU 메모리에서 모델을 명시적으로 해제합니다.
        """
        if self.model is not None:
            del self.model
            self.model = None
            import gc
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("Whisper model released from GPU memory.")
