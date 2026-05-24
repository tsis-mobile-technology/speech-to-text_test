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

    async def transcribe(self, audio_path: str, language: str = "ko") -> list[dict]:
        """
        비동기 이벤트 루프를 블로킹하지 않기 위해 ThreadPoolExecutor에서 Whisper 추론을 수행합니다.
        """
        return await asyncio.get_event_loop().run_in_executor(
            self.executor,
            self._transcribe_sync,
            audio_path,
            language
        )
        
    def _transcribe_sync(self, audio_path: str, language: str) -> list[dict]:
        self.load_model()
        
        if not WHISPER_AVAILABLE or self.model is None:
            # Mock 모드: 가짜 데이터 반환 (음성 파일 길이 기반 모의 세그먼트 생성)
            logger.warning("Whisper mock inference triggered.")
            import time
            time.sleep(2.0)  # 연산 모사
            return [
                {"start": 0.5, "end": 3.0, "text": "[Mock] 안녕하세요, 본 메시지는 STT 엔진이 모의로 작동 중일 때 출력됩니다.", "confidence": 0.95},
                {"start": 3.5, "end": 7.0, "text": "[Mock] 로컬 머신에 PyTorch 및 CUDA, faster-whisper가 올바르게 셋업되었는지 확인해 주세요.", "confidence": 0.92}
            ]

        try:
            segments, info = self.model.transcribe(
                audio_path,
                language=language,
                beam_size=settings.BEAM_SIZE,
                vad_filter=False,
                vad_parameters={"min_silence_duration_ms": settings.VAD_MIN_SILENCE_DURATION_MS}
            )
            
            result = []
            for segment in segments:
                # logprob를 신뢰도(confidence) 백분율로 모사 변환 (exp(logprob) 형태로 근사치 계산)
                import math
                conf = round(math.exp(max(segment.avg_logprob, -5.0)), 2)
                result.append({
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": segment.text.strip(),
                    "confidence": conf
                })
            return result
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
