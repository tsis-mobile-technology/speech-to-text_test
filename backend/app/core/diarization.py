import os
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from app.config import settings

logger = logging.getLogger(__name__)

try:
    from pyannote.audio import Pipeline
    import torch
    PYANNOTE_AVAILABLE = True
except ImportError:
    logger.warning("pyannote.audio is not installed. Running Diarization in mock mode.")
    PYANNOTE_AVAILABLE = False

class DiarizationEngine:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
        
    def __init__(self):
        # max_workers=1로 설정하여 화자분리 추론 역시 GPU 자원 경합을 방지하고 직렬화 처리합니다.
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.pipeline = None
        
    def load_model(self):
        """
        pyannote.audio 화자분리 파이프라인을 1회만 메모리에 로드합니다.
        """
        if self.pipeline is not None:
            return
            
        if not PYANNOTE_AVAILABLE:
            logger.warning("Mocking Pyannote Diarization Pipeline initialization...")
            return

        config_path = settings.DIARIZATION_MODEL_PATH / "config.yaml"
        logger.info(f"Checking for local Pyannote config at: {config_path}")
        
        try:
            device = torch.device(settings.WHISPER_DEVICE if torch.cuda.is_available() else "cpu")
            
            if config_path.exists():
                logger.info(f"Loading Pyannote Pipeline offline from: {config_path}")
                # 파이프라인 내부에서 참조하는 다른 원격 모델(예: 임베딩)을 위해 token 전달
                self.pipeline = Pipeline.from_pretrained(str(config_path), use_auth_token=settings.HF_TOKEN)
            else:
                logger.info("Local config.yaml not found. Loading from Hugging Face Hub...")
                if not settings.HF_TOKEN:
                    raise ValueError("HF_TOKEN is required to download pyannote/speaker-diarization-3.1 from Hugging Face Hub.")
                self.pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=settings.HF_TOKEN
                )
            
            self.pipeline.to(device)
            logger.info("Pyannote Diarization pipeline loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Pyannote Diarization model: {e}")
            self.pipeline = None

    async def diarize(self, audio_path: str) -> list[dict]:
        """
        비동기 이벤트 루프 블로킹 방지를 위해 Executor에서 화자분리 연산을 처리합니다.
        """
        return await asyncio.get_event_loop().run_in_executor(
            self.executor,
            self._diarize_sync,
            audio_path
        )
        
    def _diarize_sync(self, audio_path: str) -> list[dict]:
        self.load_model()
        
        if not PYANNOTE_AVAILABLE or self.pipeline is None:
            # Mock 모드: 임의의 화자 구간 반환
            logger.warning("Pyannote mock inference triggered.")
            import time
            time.sleep(1.5)  # 연산 모사
            return [
                {"start": 0.0, "end": 3.2, "speaker": "SPEAKER_00"},
                {"start": 3.2, "end": 8.0, "speaker": "SPEAKER_01"}
            ]

        try:
            # 추론 실행
            diarization = self.pipeline(audio_path)
            
            result = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                result.append({
                    "start": round(turn.start, 2),
                    "end": round(turn.end, 2),
                    "speaker": speaker
                })
            
            logger.info(f"Diarization complete. Found {len(result)} speech turns.")
            return result
        except Exception as e:
            logger.error(f"Error during Pyannote Diarization: {e}")
            raise e

    def release(self):
        """
        GPU 메모리에서 화자분리 모델을 강제 해제합니다.
        """
        if self.pipeline is not None:
            self.pipeline = None
            import gc
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("Pyannote model released from GPU memory.")
