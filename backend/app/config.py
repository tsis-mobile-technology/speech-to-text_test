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

    # ── Tier 3: 언어 감지 폴백 + 실시간 청크 품질 ──
    LANGUAGE_FALLBACK_THRESHOLD: float = 0.6  # 자동 감지 확률 < 0.6 → 폴백 언어로 강제 재전사
    FALLBACK_LANGUAGE: str = "ko"  # 폴백 언어 (한국어 회의 시스템 기본값)
    REALTIME_USE_INITIAL_PROMPT: bool = False  # 실시간 스트리밍에서 initial_prompt 사용 여부
                                               # (짧은 청크에서 프롬프트가 할루시네이션 유발 → 기본 비활성)
    MIN_CHUNK_DURATION_SEC: float = 1.0  # 실시간 전사 최소 버퍼 길이(초). 미만이면 전사 스킵(노이즈 방지)

    # Hallucination 필터링 설정 (Whisper 오류 텍스트 필터링)
    CONFIDENCE_THRESHOLD: float = 0.5  # ⭐ 신뢰도 < 0.5이면 제외 (상향: 0.3 → 0.5)
    NO_SPEECH_THRESHOLD: float = 0.9  # 음성 없을 확률 > 90%면 제외
    VAD_FILTER_ENABLED: bool = True  # VAD 필터 활성화 (무음 구간 자동 제거)
    MIN_SEGMENT_LENGTH: float = 0.8  # ⭐ 최소 세그먼트 길이 (초) 상향: 0.5 → 0.8
    MIN_SPEECH_DURATION: float = 1.0  # 최소 발화 길이 (초) - 이 이상만 보고
    REPETITION_THRESHOLD: float = 0.7  # ⭐ 반복 비율 70% 이상 필터링 (콤마 분리 문장)
    LOG_PROB_THRESHOLD: float = -1.0  # ⭐ 로그확률 기반 필터링 (평균 로그확률 < -1.0)
    COMPRESSION_RATIO_THRESHOLD: float = 30.0  # ⭐ 압축률 필터 (char/sec > 30 = 불가능한 속도 = 환각)

    # ── Tier 1: faster-whisper 디코딩 단계 할루시네이션 억제 (네이티브 파라미터) ──
    # 반복을 후처리로 거르기 전에 디코딩 시점에 생성 자체를 차단한다.
    CONDITION_ON_PREVIOUS_TEXT: bool = False  # 이전 텍스트 의존 제거 → 스트리밍 반복 루프 전파 차단
    NO_REPEAT_NGRAM_SIZE: int = 3  # 동일 n-gram 반복 디코딩 금지 (ㄷㄷㄷ, 네네네 차단)
    REPETITION_PENALTY: float = 1.1  # 반복 토큰 확률 패널티 (1.0 = 무패널티)
    WHISPER_COMPRESSION_RATIO_THRESHOLD: float = 2.4  # 네이티브 gzip 반복 탐지 (긴 반복 대응)
    WHISPER_LOG_PROB_THRESHOLD: float = -1.0  # 모델 내부 저신뢰 세그먼트 드롭
    WHISPER_NO_SPEECH_THRESHOLD: float = 0.6  # 모델 내부 무음 구간 드롭
    HALLUCINATION_SILENCE_THRESHOLD: float = 2.0  # 무음 뒤 할루시네이션 의심 구간 스킵 (초)

    # ── Tier 2: 문자/n-gram 단위 반복 후처리 (콤마 기반 필터 보완, '균형' 설정) ──
    CHAR_REPETITION_RATIO: float = 0.6  # 단일 문자 점유율 > 60% → 반복 (ㄷㄷㄷ, ㅋㅋㅋ)
    CHAR_DIVERSITY_MIN: float = 0.25  # 고유 문자 다양성 < 25% → 반복 (글자 종류가 거의 없음)
    NGRAM_REPETITION_RATIO: float = 0.4  # 2~4-gram 고유 비율 < 40% → 반복 (그래그래그래)
    REPETITION_MIN_LENGTH: int = 4  # 이 길이 미만 텍스트는 반복 검사 제외 (짧은 정상 발화 보호)

    # ── 자모-only 환각 필터 (완성형 한글 음절 없는 자모 텍스트 = 노이즈/환각) ──
    # 예: 'ㄷㄷ', 'ㄱㄷ', 'ㄹㄷ', 'ㄳㄷ', 'ㄲㄷ', 'ㄺㄷ', 'ㄴㄴㅇㄴ' (길이 무관 차단)
    FILTER_JAMO_ONLY: bool = True
    JAMO_RATIO_THRESHOLD: float = 0.5  # 자모 비율 > 50% → 깨진 텍스트로 간주
    
    # ── LLM 후교정 (로컬 LiteLLM 게이트웨이 경유) ──
    # 제안 아이디어: 직전 N개 문장 + 현재 STT 문장을 LLM에 넣어 문맥 기반 보정.
    LLM_CORRECTION_ENABLED: bool = os.getenv("LLM_CORRECTION_ENABLED", "true").lower() == "true"
    # Docker 컨테이너 내부 → 호스트 LiteLLM 접근: localhost 아님! host.docker.internal 사용
    LLM_API_BASE: str = os.getenv("LLM_API_BASE", "http://host.docker.internal:4000")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")          # LiteLLM 프록시 키 (.env 주입)
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")        # LiteLLM 등록 alias (→ gemma-4-E4B)
    LLM_CONTEXT_WINDOW: int = 3                              # 직전 문장 개수 (제안 그대로)
    LLM_ONLY_LOW_CONFIDENCE: bool = True                     # 저신뢰 세그먼트만 보정
    LLM_CONFIDENCE_GATE: float = 0.85                        # confidence < 이 값만 보정
    LLM_MAX_LEN_RATIO: float = 1.5                           # 교정본 길이 폭증 시 폐기(환각 가드)
    LLM_TEMPERATURE: float = 0.0                             # 결정적 출력
    LLM_TIMEOUT_SEC: float = 8.0                             # 호출 타임아웃
    LLM_MAX_TOKENS: int = 256                                # 교정문은 짧음 → 토큰 상한

    # 화자 분리 설정
    HF_TOKEN: str = os.getenv("HF_TOKEN", "")
    
    # 실시간 스트리밍 설정
    SAMPLING_RATE: int = 16000
    VAD_MIN_SILENCE_DURATION_MS: int = 500
    
    # 세션 관리 설정 (인메모리 캐시 TTL: 24시간 — 영속본은 DB에 유지됨)
    SESSION_TTL_SECONDS: int = 86400

    # ── 데이터 영속성 (Tier 4: SQLite + 파일시스템 오디오) ──
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))  # 컨테이너: /app/data (볼륨)
    DB_PATH: Path = DATA_DIR / "sessions.db"
    AUDIO_DIR: Path = DATA_DIR / "audio"                  # 회의 원본 오디오(.f32) 저장
    MAX_SESSION_DURATION_SEC: int = int(os.getenv("MAX_SESSION_DURATION_SEC", "14400"))  # 4시간 상한
    DATA_RETENTION_DAYS: int = int(os.getenv("DATA_RETENTION_DAYS", "90"))  # 영속본 보존(향후 GC)

settings = Settings()
