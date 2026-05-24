import os
from pathlib import Path
from dotenv import load_dotenv

# 루트 경로의 .env 로드
BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
load_dotenv(dotenv_path=ROOT_DIR / '.env')

class Settings:
    PROJECT_NAME: str = "온프레미스 한국어 STT 회의록 시스템"
    
    # 모델 관련 설정
    MODEL_DIR: Path = BASE_DIR / "models"
    WHISPER_MODEL_PATH: Path = MODEL_DIR / "whisper" / "faster-whisper-medium"
    DIARIZATION_MODEL_PATH: Path = MODEL_DIR / "pyannote" / "speaker-diarization-3.1"
    
    # STT 설정
    WHISPER_MODEL_SIZE: str = os.getenv("STT_MODEL_SIZE", "medium")
    WHISPER_DEVICE: str = os.getenv("STT_DEVICE", "cuda")
    WHISPER_COMPUTE_TYPE: str = os.getenv("STT_COMPUTE_TYPE", "float16")
    BEAM_SIZE: int = 1  # 실시간 처리용 (속도 최우선)
    
    # 화자 분리 설정
    HF_TOKEN: str = os.getenv("HF_TOKEN", "")
    
    # 실시간 스트리밍 설정
    SAMPLING_RATE: int = 16000
    VAD_MIN_SILENCE_DURATION_MS: int = 500
    
    # 세션 관리 설정 (TTL: 24시간)
    SESSION_TTL_SECONDS: int = 86400

settings = Settings()
