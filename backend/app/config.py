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

    # Beam size 프로필 (웹 검증 기반)
    BEAM_SIZE_FAST: int = 1          # 실시간 스트리밍용 (레이턴시 < 2초)
    BEAM_SIZE_BALANCED: int = 3      # 파일 업로드용 (정확도 20-30% 향상) ⭐ 권장
    BEAM_SIZE_HIGH: int = 5          # 고정확도 모드 (정확도 중심, 속도 느림)

    # 음성 인식 파라미터 (웹 검증)
    TEMPERATURE: list = [0.0, 0.2, 0.4, 0.6]  # 모델이 여러 후보 생성 후 최고 신뢰도 선택

    # 도메인별 Language Prompt (문맥 정보)
    CONTEXT_PROMPTS: dict = {
        "meeting": "회의, 발언, 논의, 결정, 액션아이템, 안건, 참석자, 보고",
        "technical": "기술, API, 데이터베이스, 서버, 배포, 클라우드, 마이크로서비스",
        "general": "안녕하세요, 감사합니다, 확인했습니다, 네, 알겠습니다",
        "bilingual": "회의, meeting, 발언, discussion, 결정, decision, API, 데이터베이스, database, 안녕하세요, hello, 감사합니다, thank you",  # 영어-한국어 혼합용
    }

    # 언어 감지 설정
    AUTO_DETECT_LANGUAGE: bool = True  # 언어 자동 감지 활성화
    LANGUAGE_DETECTION_THRESHOLD: float = 0.5  # 신뢰도 낮으면 경고

    # Hallucination 필터링 설정 (Whisper 오류 텍스트 필터링)
    CONFIDENCE_THRESHOLD: float = 0.5  # ⭐ 신뢰도 < 0.5이면 제외 (상향: 0.3 → 0.5)
    NO_SPEECH_THRESHOLD: float = 0.9  # 음성 없을 확률 > 90%면 제외
    VAD_FILTER_ENABLED: bool = True  # VAD 필터 활성화 (무음 구간 자동 제거)
    MIN_SEGMENT_LENGTH: float = 0.8  # ⭐ 최소 세그먼트 길이 (초) 상향: 0.5 → 0.8
    MIN_SPEECH_DURATION: float = 1.0  # 최소 발화 길이 (초) - 이 이상만 보고
    REPETITION_THRESHOLD: float = 0.7  # ⭐ 반복 비율 70% 이상 필터링
    LOG_PROB_THRESHOLD: float = -1.0  # ⭐ 로그확률 기반 필터링 (평균 로그확률 < -1.0)
    COMPRESSION_RATIO_THRESHOLD: float = 30.0  # ⭐ 압축률 필터 (char/sec > 30 = 불가능한 속도 = 환각)
    
    # 화자 분리 설정
    HF_TOKEN: str = os.getenv("HF_TOKEN", "")
    
    # 실시간 스트리밍 설정
    SAMPLING_RATE: int = 16000
    VAD_MIN_SILENCE_DURATION_MS: int = 500
    
    # 세션 관리 설정 (TTL: 24시간)
    SESSION_TTL_SECONDS: int = 86400

settings = Settings()
