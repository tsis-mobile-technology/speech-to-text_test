# LLM 기반 STT 후처리(문맥 보정) 검토 노트

> 작성일: 2026-05-30 (업데이트: 로컬 LiteLLM 연결 설계 반영)
> 상태: **✅ 구현 완료 (배치+실시간) · 컨테이너 내부 E2E 검증 OK**
> 제안자 아이디어:
> 1. STT 결과를 가져온다.
> 2. 직전 텍스트 3개 + 방금 나온 STT 텍스트를 LLM에 넣어, 문맥을 고려해 최적의 텍스트로 보정한다.
> **연결 방식: 로컬 LiteLLM 프록시 경유 (자세한 설계는 §4.6)**

## ✅ 구현 완료 (2026-05-30) — 결정: 실시간까지 한 번에 / 저신뢰만 / extra_hosts 추가
- **신규** `backend/app/core/llm_corrector.py`: `LLMCorrector` 싱글턴(OpenAI 호환 클라, 자체 ThreadPool, 실패 시 원문 폴백, 길이 가드).
- **config.py**: `LLM_*` 설정군 추가(enabled/base/key/model/context_window/confidence_gate/len_ratio/temp/timeout).
- **모델**: `TranscriptSegment`에 `original_text`, `corrected` 필드 추가(원문 보존).
- **배치**: `pipeline.py` `apply_llm_correction()` — align 후 저신뢰(conf<0.85) 세그먼트만 보정.
- **실시간**: `websocket.py` — `final` 전송 후 저신뢰 세그먼트를 비동기 보정 → `corrected` 메시지로 텍스트 교체(세션 객체 참조 갱신).
- **프론트**: `SessionContext`가 `corrected` 메시지 처리(텍스트 교체), `page.tsx`에 `✨ AI 보정` 배지(hover 시 원문).
- **인프라**: `docker-compose.yml` backend에 `extra_hosts: host.docker.internal:host-gateway`; `.env`에 `LLM_*` 주입(키=LiteLLM master_key); `requirements.txt`에 `openai`.
- **검증**(재빌드 후): 컨테이너 내부→`host.docker.internal:4000` 연결 OK, "햇습니다"→"했습니다." 보정, 게이트(0.95 미보정/0.6 보정) 정상, 배치 패스 원문 보존 확인, 프론트 컴파일 OK.
- **남은 검증(사용자)**: 실제 마이크/파일로 보정 품질·지연 체감, 과교정 여부 모니터링(`✏️ LLM 보정`, `🚫 LLM 교정 폐기` 로그).

---

## 0. 한 줄 결론

**타당하고 업계에서 검증된 방향(GER, Generative Error Correction)이다. 온프레미스 RTX 3060 환경에서도 구현 가능하나, "실시간 스트리밍"이 아니라 "파일/배치 모드" 또는 "비동기 2단계 보정"으로 시작하는 것이 안전하다.** 핵심 리스크는 (a) LLM의 과교정/환각, (b) 단일 GPU에서 Whisper·pyannote와의 VRAM/지연 경쟁이다.

---

## 1. 이 아이디어가 무엇인가 (학술/업계 명칭)

제안한 방식은 정확히 **Post-ASR Generative Error Correction (GER)** / **LLM 기반 ASR 오류 교정**이라는 확립된 기법이다. STT(음향 모델)가 1차 전사를 만들고, LLM(언어 모델)이 문맥·문법·도메인 지식으로 오류를 교정한다.

특히 제안의 "직전 3개 문장을 문맥으로" 부분은 **대화 문맥 인지 교정(conversation-aware correction)** 에 해당하며, 회의록처럼 연속 발화에서 효과가 큰 방식이다.

> 참고: 현재 우리 시스템은 할루시네이션 방지를 위해 Whisper 내부의 `condition_on_previous_text=False`로 문맥 의존을 **껐다**. 이 아이디어는 문맥을 Whisper 디코더가 아니라 **별도 LLM 계층에서 통제된 형태로 다시 활용**하는 것이라 설계상 깔끔하게 양립한다.

---

## 2. 실제 사례 (검색 확인)

| 사례 | 내용 | 시사점 |
|------|------|--------|
| **Can Generative LLMs perform ASR error correction?** (arXiv 2307.04172) | ChatGPT 류 LLM으로 zero/few-shot ASR 교정 실험 | 프롬프트만으로도 교정 효과 입증. 단, 과교정 위험 경고 |
| **Whispering-LLaMA** (EMNLP 2023, GitHub 공개) | Whisper 인코더 + LLaMA 디코더 융합 교정. **WER 상대 37.66% 개선** | 강력하나 학습/융합 필요(난도 높음) |
| **GenSEC Challenge** (arXiv 2409.09785) | post-ASR 교정·화자태깅·감정인식 공식 벤치마크 | 후처리가 독립 연구 분야로 자리잡음. 베이스라인 코드 존재 |
| **ClozeGER / "Listen Again"** (arXiv 2405.10025) | N-best 가설 + 음성 재참조로 교정 | N-best 활용 시 정확도↑ (우리 Whisper도 n-best 출력 가능) |
| **Flan-T5 / Qwen2 post-correction** | 소형 모델 파인튜닝으로 ASR 후교정 | **소형 모델로도 가능** → 온프레미스 적합 |
| **Korean Spoken QA, ASR-LLM Cascade** (arXiv 2605.17443) | 한국어는 **단일 음절/한 글자 오류**가 의미를 바꿈(동음이의 한자어). ASR 오류가 downstream으로 전파 | 한국어 후교정의 **효용이 특히 큼**. 동시에 한 글자 교정의 민감성도 큼 |
| **Qwen3-ASR** (Alibaba, 오픈소스) | 한국어 포함 30+ 언어 ASR | (대안) 엔진 자체 교체 옵션 — 본 아이디어와 별개 |

**핵심 교훈 2가지**
- (+) 한국어는 후교정 효용이 크다(동음이의·조사 오류 교정).
- (–) 연구들이 공통적으로 **과교정(over-correction)/환각**을 경고한다. "원문에 없는 내용을 LLM이 지어냄"이 가장 큰 실패 모드.

---

## 3. 온프레미스 타당성 검토 (RTX 3060 12GB / RAM 82GB / 클라우드 금지)

### 3.1 VRAM 예산
현재 사용: Whisper medium ~3GB + pyannote ~1.5GB + 추론 텐서 ~1GB = **~5.5GB**, 여유 **~6.5GB**.

| 배치 위치 | 후보 모델(예) | 대략 VRAM(Q4) | 비고 |
|-----------|--------------|--------------|------|
| GPU 동거 | Qwen2.5-3B-Instruct | ~2.5GB | 여유 6.5GB 내 OK |
| GPU 동거 | Llama-3.2-3B / Gemma-2-2B | ~2~3GB | OK |
| GPU 동거(빠듯) | Qwen2.5-7B-Instruct Q4 | ~5GB | Whisper+pyannote와 합치면 위험, 동시 추론 시 OOM 우려 |
| GPU 불가 | EEVE-Korean-10.8B Q4 | ~6.5GB | Whisper 로딩 상태에선 **불가** |
| **CPU 오프로드(권장)** | 위 모델들 llama.cpp(GGUF) | VRAM 0 | RAM 82GB 활용, **VRAM 경쟁 없음**. 속도는 느림(수~수십 tok/s) |

→ **권장: 소형 한국어 가능 instruct 모델을 (a) GPU에 소형(3B 이하)으로 동거 또는 (b) CPU(llama.cpp)로 오프로드.** 단일 GPU에서 Whisper 추론과 LLM 추론이 동시에 경쟁하지 않도록 직렬화 필요(현 `ThreadPoolExecutor max_workers=1` 패턴 확장).

### 3.2 지연(Latency) — 가장 중요한 제약
- **실시간 스트리밍**: 현재 청크 처리 ~0.5~6초. 여기에 LLM 교정(문장당 수백 ms~수초)을 **동기로 끼우면 레이턴시 목표(<2초)를 깨기 쉽다.**
- **권장 패턴 (2단계, 우리 구조에 적합)**:
  1. 1차: 원본 STT를 즉시 `partial`/`final`로 표시 (지금처럼).
  2. 2차: LLM 보정 결과를 **비동기**로 만들어 `corrected` 메시지로 교체 표시.
  - 우리는 이미 `partial`→`final`→`speaker_updated` 교체 UI 패턴이 있어 **`corrected` 타입 추가가 자연스럽다.**
- **파일/배치 모드**: 지연 비민감 → **여기서부터 도입하는 것이 가장 안전하고 효과 확실.**

### 3.3 보안
모든 후보(Qwen, EEVE, Llama, Gemma)는 오픈소스 로컬 실행 가능(llama.cpp/Ollama/vLLM/transformers). **클라우드 API 불필요 → 프로젝트의 "외부 API 완전 배제" 원칙 충족.** ✅

---

## 4. 제안 설계 (구현 시 — 아직 구현 안 함)

### 4.1 삽입 위치
```
STT 세그먼트 생성 → (기존 할루시네이션 필터) → ★ LLM 문맥 보정 ★ → 화자 정렬/세션 저장
```
- 신규 모듈: `backend/app/core/llm_corrector.py` (싱글턴, `stt_engine.py` 패턴 모방)
- 배치: `pipeline.py` / `transcribe.py`에서 정렬 후 보정 패스 1회
- 실시간: `websocket.py`에서 비동기 보정 → `type:"corrected"` 송신(선택)

### 4.2 입력 구성 (제안 아이디어 그대로)
- 직전 확정 세그먼트 N개(기본 3) + 현재 세그먼트 텍스트를 슬라이딩 윈도우로 구성.
- 회의 도메인 용어 사전/프롬프트를 함께 제공(현 `CONTEXT_PROMPTS` 재활용 가능).

### 4.3 프롬프트 예시 (한국어, 보수적 교정 — 과교정 방지)
```
당신은 한국어 회의록 STT 결과를 교정하는 도구입니다.
규칙:
- 발화에 없는 내용을 새로 추가하지 마세요. (환각 금지)
- 명백한 오타/띄어쓰기/동음이의 오류만 문맥에 맞게 수정하세요.
- 의미가 불확실하면 원문을 그대로 두세요.
- 출력은 교정된 현재 문장만. 설명 금지.

[직전 문맥]
{prev_1}
{prev_2}
{prev_3}
[교정할 현재 문장]
{current}
[교정 결과]
```

### 4.4 안전장치 (연구들의 과교정 경고 대응)
- **신뢰도 게이팅**: confidence가 높은 세그먼트는 건너뛰고, 낮은(애매한) 세그먼트만 보정 → 비용·리스크↓
- **원문 보존**: 원본과 교정본을 둘 다 저장(`text` / `text_corrected`), UI에서 토글/비교 가능
- **편집 거리 가드**: 교정본이 원문 대비 과도하게 길어지거나(예: 길이 1.5배↑) 편집거리가 너무 크면 교정 폐기 → 환각 차단
- **GPU 직렬화**: LLM·Whisper 동시 추론 금지(큐잉) 또는 LLM은 CPU 오프로드

### 4.5 신규 설정(config) 초안 — **로컬 LiteLLM 연결 기준**
```python
# ── LLM 후교정 (로컬 LiteLLM 게이트웨이 경유) ──
LLM_CORRECTION_ENABLED: bool = False                  # 기본 off, 단계적 활성화
# Docker 컨테이너 내부 → 호스트의 LiteLLM 접근: localhost 아님! host.docker.internal 사용
LLM_API_BASE: str = os.getenv("LLM_API_BASE", "http://host.docker.internal:4000")
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")       # LiteLLM 프록시 키 (.env에서 주입)
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")     # ⚠️ LiteLLM 등록 alias명 = "gpt-4o"
                                                       # (→ host:8080 의 google_gemma-4-E4B-it-Q8_0.gguf로 라우팅)
LLM_CONTEXT_WINDOW: int = 3                            # 직전 문장 개수 (제안 그대로)
LLM_ONLY_LOW_CONFIDENCE: bool = True                  # 저신뢰 세그먼트만 보정
LLM_CONFIDENCE_GATE: float = 0.85                      # 이 미만만 보정
LLM_MAX_LEN_RATIO: float = 1.5                         # 길이 폭증 시 교정 폐기(환각 가드)
LLM_TEMPERATURE: float = 0.0                           # 결정적 출력(교정은 창의성 불필요)
LLM_TIMEOUT_SEC: float = 8.0                           # 호출 타임아웃(실시간은 더 짧게)
```

> 모델 호스팅(Whisper와의 VRAM 경쟁, CPU/GPU 배치)은 **LiteLLM/Ollama 측 책임으로 분리**된다.
> STT 백엔드는 LiteLLM에 HTTP로 요청만 하므로 모델 교체가 환경변수 변경만으로 가능.

---

## 4.6 로컬 LiteLLM 연결 설계 (현재 환경 기준)

### 발견된 로컬 환경 (2026-05-30 probe — ✅ 연결 검증 완료)
| 항목 | 값 |
|------|-----|
| LiteLLM 프록시 | `litellm-proxy` 컨테이너, `http://localhost:4000` (OpenAI 호환). 컨테이너 내부에선 `http://host.docker.internal:4000` |
| **등록 모델(LiteLLM)** | **`gpt-4o`** (alias) → `litellm_params.api_base: http://host.docker.internal:8080` 로 라우팅 |
| 실제 서빙 모델 | `host:8080`의 OpenAI 호환 서버(llama.cpp 등)가 **google_gemma-4-E4B-it-Q8_0.gguf** 서빙 |
| API 키 | **확보·검증됨** — LiteLLM `general_settings.master_key` = `sk-local-…`(15자). `/v1/models` 200 OK |
| 참고 | Ollama(`:11434`)에도 별도 모델 다수 존재하나, **현재 LiteLLM은 :8080만 라우팅**. Ollama를 쓰려면 LiteLLM config에 model 추가 필요 |

### ✅ End-to-End 연결 검증 (2026-05-30)
```
POST http://localhost:4000/v1/chat/completions  (model="gpt-4o", Bearer sk-local-…)
입력(현재): "마케팅 팀에서 광고 예산을 더 늘려야 한다고 햇습니다"
출력(교정): "마케팅 팀에서 광고 예산을 더 늘려야 한다고 했습니다."   ← 오타만 수정, 내용 추가 없음 ✅
```
→ 로컬 LiteLLM 경유 한국어 STT 교정이 **실제로 동작함**을 확인. (gemma-4-E4B, temperature=0)

### 🔑 키 주입 방법 (구현 시)
LiteLLM master_key는 `litellm-proxy` 컨테이너의 `/app/config.yaml > general_settings.master_key`에 있음.
운영 권장: master_key를 직접 쓰기보다 **전용 virtual key 발급** 후 `.env`의 `LLM_API_KEY`에 주입.
(빠른 PoC라면 master_key 그대로 사용 가능 — 로컬 dev 키)

### ⚠️ Docker 네트워킹 (필수)
STT 백엔드는 컨테이너 내부에서 동작 → 컨테이너의 `localhost`는 호스트가 아님.
`docker-compose.yml` backend 서비스에 호스트 접근 경로를 추가해야 한다:
```yaml
  backend:
    extra_hosts:
      - "host.docker.internal:host-gateway"   # 컨테이너 → 호스트 LiteLLM(:4000) 접근
```
그 후 컨테이너 내부에서 `http://host.docker.internal:4000`로 LiteLLM 호출.

### 연결 방식: OpenAI 호환 클라이언트 (LiteLLM은 OpenAI API 스펙 제공)
별도 무거운 의존성 없이 `openai` 파이썬 클라이언트(또는 `httpx`)로 호출 가능.
`requirements.txt`에 `openai` 추가만 하면 됨(LiteLLM SDK 자체는 백엔드에 불필요 — 프록시가 이미 호스트에서 동작).

```python
# backend/app/core/llm_corrector.py (초안, 구현 예정)
from openai import OpenAI
from app.config import settings

class LLMCorrector:
    _instance = None
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.client = OpenAI(
            base_url=settings.LLM_API_BASE,   # http://host.docker.internal:4000
            api_key=settings.LLM_API_KEY,     # LiteLLM 프록시 키
            timeout=settings.LLM_TIMEOUT_SEC,
        )

    def correct(self, current_text: str, prev_texts: list[str]) -> str:
        ctx = "\n".join(prev_texts[-settings.LLM_CONTEXT_WINDOW:])
        resp = self.client.chat.completions.create(
            model=settings.LLM_MODEL,         # 예: "qwen3.5:9b"
            temperature=settings.LLM_TEMPERATURE,
            messages=[
                {"role": "system", "content": "한국어 회의록 STT 교정기. 발화에 없는 내용 추가 금지, "
                                              "명백한 오타/띄어쓰기/동음이의 오류만 수정, 불확실하면 원문 유지, "
                                              "교정된 현재 문장만 출력."},
                {"role": "user", "content": f"[직전 문맥]\n{ctx}\n[교정할 현재 문장]\n{current_text}\n[교정 결과]"},
            ],
        )
        return resp.choices[0].message.content.strip()
```

### .env 추가 항목 (검증된 값 기준)
```
LLM_API_BASE=http://host.docker.internal:4000
LLM_API_KEY=sk-local-…              # litellm-proxy /app/config.yaml 의 master_key (또는 발급한 virtual key)
LLM_MODEL=gpt-4o                    # LiteLLM 등록 alias (→ gemma-4-E4B)
```

### LiteLLM 사용의 이점
- STT 백엔드에 무거운 모델/추론 코드 불필요 → **결합도↓, 모델 교체는 env 변경만**.
- OpenAI 호환이라 표준 클라이언트·재시도·타임아웃 그대로 활용.
- VRAM/CPU 배치는 LiteLLM·Ollama 운영 영역으로 분리 → STT의 GPU 직렬화 로직과 독립.
- 향후 모델 업그레이드(gpt-oss, qwen 대형)도 STT 코드 변경 없이 가능.

### LiteLLM 경유 시 유의점
- **VRAM 경쟁(여전히 존재)**: Ollama 모델도 같은 GPU를 쓰면 Whisper(5.5GB)와 충돌. → Ollama를 CPU 모드/별도 GPU로 두거나, STT 추론과 LLM 호출 시점을 겹치지 않게(예: 세션 종료 후 배치 교정) 운영.
- **가용성/타임아웃**: LiteLLM 다운 시 STT는 원문으로 폴백(교정 실패해도 전사 결과는 보존).
- **모델명 일치**: `LLM_MODEL`은 Ollama 태그가 아니라 **LiteLLM에 등록된 model_name**이어야 함(둘이 다를 수 있음 → `/v1/models`로 확인).

---

## 5. 구현 난도 / 권장 로드맵

| 단계 | 내용 | 난도 | 효과/리스크 |
|------|------|------|------------|
| **A. 배치 모드 프롬프트 교정** | 파일 업로드 결과에 LLM 후교정(zero-shot) | ★★☆ | 효과 확실·리스크 낮음 → **여기서 시작 권장** |
| B. 안전장치 추가 | 신뢰도 게이팅 + 편집거리 가드 + 원문 보존 | ★★☆ | 과교정 방지 |
| C. 실시간 비동기 보정 | `corrected` 메시지 2단계 표시 | ★★★ | UX 향상, 지연 관리 필요 |
| D. (고급) 파인튜닝/ N-best 융합 | 한국어 ASR 오류쌍 학습 or Whisper n-best 활용 | ★★★★ | 최고 정확도, 데이터·학습 비용 큼 |

권장: **A→B로 배치 모드 검증 → C로 실시간 확장.** D는 정확도 한계 도달 시 고려.

---

## 6. 대안/보완 (LLM이 과하다면)
- **경량 규칙/사전 기반 교정**: 회의 도메인 용어 치환 사전 + 한국어 맞춤법 검사기(예: 형태소 기반). LLM보다 가볍고 환각 0. 효과는 제한적.
- **Whisper `initial_prompt`에 도메인 용어 강화**: 이미 부분 활용 중. 후교정 없이 1차 정확도 일부 개선.
- **엔진 교체 검토**: Qwen3-ASR 등 최신 다국어 ASR (별도 PoC 필요, 본 아이디어와 독립).

---

## 7. 컨펌이 필요한 결정 사항 (구현 착수 시) — LiteLLM 연결 기준
1. **LiteLLM API 키**: ✅ 확보·검증 (`sk-local-…` master_key). 운영 시 virtual key 발급 권장.
2. **모델**: ✅ 확정·검증 — LiteLLM alias `gpt-4o` (→ google_gemma-4-E4B gguf).
3. 도입 범위: **배치(파일) 모드부터**(권장) vs 실시간까지 한 번에? ← **결정 필요**
4. 보정 범위: 전체 세그먼트 vs **저신뢰 세그먼트만**(권장)? ← **결정 필요**
5. `docker-compose.yml`에 `extra_hosts: host.docker.internal:host-gateway` 추가 동의? ← **결정 필요**(재빌드 동반)

### 구현 착수 시 작업 목록(예고)
- `requirements.txt`에 `openai` 추가
- `backend/app/core/llm_corrector.py` 신규(싱글턴, §4.6 초안)
- `config.py`에 §4.5 설정 추가, `.env`에 키/모델/베이스URL 추가
- `docker-compose.yml`에 `extra_hosts` 추가 → **재빌드**(`up -d --build`)
- 배치 경로(`transcribe.py`/`pipeline.py`)에 보정 패스 삽입(원문 보존 + 안전장치)
- 연결 검증: 컨테이너 내부에서 LiteLLM `/v1/models` 200 확인 후 교정 1건 테스트

---

## 8. 참고 자료 (검색 출처)
- Can Generative LLMs perform ASR error correction? — https://arxiv.org/pdf/2307.04172
- LLM-based Generative Error Correction (GenSEC) — https://arxiv.org/pdf/2409.09785
- Whispering-LLaMA (EMNLP'23) — https://arxiv.org/pdf/2310.06434 / https://github.com/srijith-rkr/whispering-llama
- Listen Again and Choose the Right Answer (ClozeGER) — https://arxiv.org/pdf/2405.10025
- Korean Spoken QA, ASR–LLM Cascade 오류 전파 분석 — https://arxiv.org/abs/2605.17443
- EEVE-Korean (Vocabulary Expansion) — https://arxiv.org/pdf/2402.14714
- Qwen3-ASR (오픈소스 다국어 ASR) — https://github.com/QwenLM/Qwen3-ASR/
