import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from app.config import settings

logger = logging.getLogger(__name__)

# openai 클라이언트가 설치/구성된 경우에만 사용 (없으면 보정 비활성, STT 원문 그대로)
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    logger.warning("openai 패키지 없음 → LLM 후교정 비활성(원문 유지).")
    OPENAI_AVAILABLE = False


_SYSTEM_PROMPT = (
    "당신은 한국어 회의록 STT 결과를 교정하는 도구입니다.\n"
    "규칙:\n"
    "- 발화에 없는 내용을 새로 추가하지 마세요. (환각 금지)\n"
    "- 명백한 오타/띄어쓰기/동음이의 오류만 문맥에 맞게 수정하세요.\n"
    "- 의미가 불확실하면 원문을 그대로 두세요.\n"
    "- 설명·따옴표 없이 교정된 현재 문장만 출력하세요."
)


class LLMCorrector:
    """
    로컬 LiteLLM(OpenAI 호환) 게이트웨이를 통해 STT 세그먼트를 문맥 기반으로 보정한다.
    - 직전 N개 문장(context) + 현재 문장을 입력으로 사용.
    - 실패/타임아웃/LiteLLM 다운 시 항상 원문으로 폴백(전사 결과 보존).
    - 과교정 방지: 길이 비율 가드.
    GPU 추론(Whisper/pyannote)과 분리된 자체 ThreadPoolExecutor를 사용해
    STT 추론 큐(max_workers=1)를 막지 않는다.
    """
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._client = None
        # 네트워크 IO 전용 (GPU executor와 별개)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="llm-corrector")

    def is_enabled(self) -> bool:
        if not settings.LLM_CORRECTION_ENABLED:
            return False
        if not OPENAI_AVAILABLE:
            return False
        if not settings.LLM_API_KEY:
            logger.warning("LLM_API_KEY 미설정 → LLM 후교정 비활성.")
            return False
        return True

    def _get_client(self):
        if self._client is None:
            self._client = OpenAI(
                base_url=settings.LLM_API_BASE,
                api_key=settings.LLM_API_KEY,
                timeout=settings.LLM_TIMEOUT_SEC,
                max_retries=0,  # 실시간성 위해 재시도 없음(실패 시 원문 폴백)
            )
        return self._client

    @staticmethod
    def _worth_correcting(text: str) -> bool:
        """교정 가치가 있는 텍스트인지(완성형 한글 음절 or 2자+ 영단어 + 최소 길이)."""
        t = (text or "").strip()
        if len(t) < 2:
            return False  # '네','음' 등 초단문은 교정 불필요
        if any("가" <= c <= "힣" for c in t):
            return True   # 완성형 한글 포함
        import re
        return bool(re.search(r"[A-Za-z]{2,}", t))  # 영단어 포함

    def should_correct(self, confidence: float, text: str = "") -> bool:
        """저신뢰 + 교정 가치 있는 세그먼트만 보정 (garbage/초단문 제외)."""
        if not self.is_enabled():
            return False
        if text and not self._worth_correcting(text):
            return False
        if settings.LLM_ONLY_LOW_CONFIDENCE:
            return confidence < settings.LLM_CONFIDENCE_GATE
        return True

    def correct_sync(self, current_text: str, prev_texts: list[str]) -> str:
        """
        동기 보정. 어떤 이유로든 실패하면 원문(current_text)을 그대로 반환한다.
        """
        original = (current_text or "").strip()
        if not original or not self.is_enabled():
            return original

        try:
            ctx = "\n".join(t.strip() for t in prev_texts[-settings.LLM_CONTEXT_WINDOW:] if t and t.strip())
            user_msg = (
                f"[직전 문맥]\n{ctx if ctx else '(없음)'}\n"
                f"[교정할 현재 문장]\n{original}\n[교정 결과]"
            )
            resp = self._get_client().chat.completions.create(
                model=settings.LLM_MODEL,
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            )
            corrected = (resp.choices[0].message.content or "").strip()
            corrected = corrected.strip('"“”\'`').strip()

            if not corrected:
                return original

            # 과교정/환각 가드: 길이가 비정상적으로 늘어나면 폐기
            if len(corrected) > max(len(original) * settings.LLM_MAX_LEN_RATIO, len(original) + 10):
                logger.warning(
                    f"🚫 LLM 교정 폐기(길이 폭증, 환각 의심): "
                    f"{len(original)}→{len(corrected)}자 - '{corrected[:50]}'"
                )
                return original

            if corrected != original:
                logger.info(f"✏️ LLM 보정: '{original[:40]}' → '{corrected[:40]}'")
            return corrected

        except Exception as e:
            logger.warning(f"⚠️ LLM 보정 실패(원문 유지): {e}")
            return original

    async def correct_async(self, current_text: str, prev_texts: list[str]) -> str:
        """비동기 컨텍스트(파이프라인/WebSocket)에서 이벤트 루프를 막지 않고 보정."""
        return await asyncio.get_event_loop().run_in_executor(
            self.executor, self.correct_sync, current_text, prev_texts
        )
