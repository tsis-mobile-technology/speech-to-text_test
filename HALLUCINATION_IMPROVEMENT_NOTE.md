# 할루시네이션 품질 개선 노트 (실시간 STT)

> 작성일: 2026-05-30
> 상태: **Tier 1 + 2 + 3 구현 완료 (재빌드·런타임 검증 OK)**
> 트리거 로그: 실시간 스트리밍 중 `ㄷㄷㄷㄷㄷ...`(ㄷ 50회 반복) 출력

## 🔧 구현 결과 (2026-05-30)
- **Tier 1 적용**: `stt_engine.py` `model.transcribe()`에 네이티브 파라미터 7종 추가
  (`condition_on_previous_text=False`, `no_repeat_ngram_size=3`, `repetition_penalty=1.1`,
  `compression_ratio_threshold=2.4`, `log_prob_threshold=-1.0`, `no_speech_threshold=0.6`,
  `hallucination_silence_threshold=2.0`)
- **Tier 2 적용**: `_is_repetitive_text()` 헬퍼 추가 + 최종 검증 루프에 통합 (문자/n-gram 반복 탐지)
- **Tier 3 적용**:
  - 언어 폴백 — `_transcribe_sync`에서 자동 감지 확률 < 0.6이면 `ko` 강제 재전사
    (transcribe를 `_run_transcribe(lang)` 헬퍼로 추출, info는 제너레이터 소비 전 계산되어 폴백 비용 최소)
  - 실시간 청크 품질 — `websocket.py`: initial_prompt 기본 비활성(`REALTIME_USE_INITIAL_PROMPT=False`),
    최소 버퍼 길이 가드(`MIN_CHUNK_DURATION_SEC=1.0`, 미만이면 clear 없이 누적 후 스킵)
- **설정 노출**: `config.py`에 Tier 1/2/3 임계값 전부 노출 (균형 설정)
- **검증**:
  - 반복 탐지 단위 테스트 10/10 통과(정상 발화 보존)
  - faster-whisper 1.2.1 파라미터 7종 + `TranscriptionInfo.language_probability` 호환 확인
  - **재빌드 후 런타임 스모크**: 노이즈 입력 → `언어 감지 불안정 (en @ 0.54 < 0.6) → 'ko' 강제 재전사` 발동,
    최종 0 세그먼트(할루시네이션 미발생) 확인 ✅
- **남은 검증(사용자)**: 실제 마이크 스트리밍으로 `ㄷㄷㄷ` 미재현 + 정상 발화 과필터/레이턴시 영향 로그 확인

## ⚠️ 배포 주의 (중요)
백엔드는 소스코드를 **이미지에 빌드 시점에 굽는다**(docker-compose는 `./backend/models`만 마운트, 소스 미마운트).
→ 코드 변경 후 `docker compose restart`로는 **반영 안 됨**. 반드시 **`docker compose up -d --build backend`** 로 재빌드.

## ✅ 확정된 결정 (2026-05-30)
1. **언어 전략**: 자동 감지 + 폴백 — 감지 확률 < 0.6이면 `ko`로 강제 재전사
2. **적용 순서**: Tier 1+2 먼저 구현 → 검증 → Tier 3 진행 (완료)
3. **필터 공격성**: 균형 (config로 튜닝 가능하게 노출)

---

## 1. 문제 현상 요약

```
[INFO] stt_engine: 🌐 언어 자동 감지 활성화
[INFO] faster_whisper: Processing audio with duration 00:03.840
[INFO] faster_whisper: VAD filter removed 00:00.544 of audio
[INFO] faster_whisper: Detected language 'ko' with probability 0.52   ← 감지 신뢰도 매우 낮음
[INFO] stt_engine: ✅ 감지된 언어: ko
[INFO] websocket: ⏱️ 처리 시간: 6456ms (Whisper: 6455ms)               ← 3.84초 오디오에 6.4초 추론(과도)
[INFO] websocket: ✅ Sent final: ㄷㄷㄷㄷㄷㄷㄷㄷㄷㄷㄷㄷㄷㄷㄷㄷㄷㄷㄷㄷ...   ← 전형적 반복 할루시네이션
```

두 가지 신호가 동시에 나타남:
1. **언어 감지 신뢰도 0.52** (불안정) — 실제 음성인데 모델이 확신을 못 함
2. **단일 자모 반복 할루시네이션** (`ㄷ` × 50) — 디코딩 루프에 빠진 전형적 패턴

---

## 2. 근본 원인 분석 (왜 기존 5중 필터를 통과했는가)

현재 `stt_engine.py`의 필터를 `ㄷ×50` 세그먼트(약 3초)에 적용해 추적:

| 필터 | 임계값 | `ㄷ×50` 통과 여부 | 사유 |
|------|--------|------------------|------|
| ① log_prob | < -1.0 | **통과(못 잡음)** | 반복 토큰은 오히려 모델이 "확신" → logprob 높음 |
| ② confidence | < 0.5 | **통과** | 위와 동일, 신뢰도 높게 나옴 |
| ③ 최소 길이 | < 0.8s | **통과** | 세그먼트 ~3초로 충분히 김 |
| ④ no_speech_prob | > 0.9 | **통과** | 실제 음성 있음 → 낮음 |
| ⑤ 압축률(char/sec) | > 30 | **통과** | 50자/3초 ≈ 16.7 < 30 |
| ⑥ 반복(콤마 분리) | 70% | **통과(구조적 한계)** | `ㄷㄷㄷ`엔 콤마가 없어 `words=[전체]`, len=1 → 검사 자체 스킵 |

**핵심 결론 3가지:**

- **(A) 반복 탐지가 콤마 기반이라 문자/토큰 단위 반복(`ㄷㄷㄷ`, `ㅋㅋㅋ`, `네네네`)을 원천적으로 못 잡음.** 현재 로직은 `"안녕하세요, 안녕하세요"`처럼 콤마로 나뉜 문장 반복만 검출.
- **(B) faster-whisper의 디코딩 단계 할루시네이션 억제 파라미터를 전혀 안 쓰고 있음.** `model.transcribe()`에 `vad_filter`만 전달. `condition_on_previous_text`, `no_repeat_ngram_size`, `repetition_penalty`, `compression_ratio_threshold`, `log_prob_threshold`, `no_speech_threshold`, `hallucination_silence_threshold` 미사용 → **후처리(post-filter)로 막기 전에 애초에 반복을 안 만들게 하는 게 훨씬 효과적.**
- **(C) 언어 자동 감지가 짧은/모호한 청크에서 불안정(0.52).** 한국어 회의 시스템인데 청크마다 언어를 다시 추정 → 잘못 감지 시 할루시네이션 유발. CLAUDE.md 원안은 `language="ko"` 강제를 권장했으나 현재 코드는 auto-detect로 변경됨.

> 추가 검증: gzip 압축률은 짧은 반복(`ㄷ×50`)에서 1.92로 네이티브 임계값 2.4에도 미달 → 압축률만으론 짧은 반복을 못 잡음. **디코딩 단계 `no_repeat_ngram_size` + 문자 반복 후처리 병행이 가장 확실함.**

---

## 3. 개선 계획 (3 Tier)

### Tier 1 — 디코딩 단계에서 반복을 원천 차단 (최우선, 근본 해결)

`stt_engine._transcribe_sync()`의 `model.transcribe()` 호출에 네이티브 파라미터 추가:

```python
segments, info = self.model.transcribe(
    audio_path,
    language=whisper_language,
    beam_size=beam_size,
    temperature=settings.TEMPERATURE,
    initial_prompt=initial_prompt,
    vad_filter=settings.VAD_FILTER_ENABLED,
    vad_parameters={"min_silence_duration_ms": settings.VAD_MIN_SILENCE_DURATION_MS},
    # ▼▼ 신규 (할루시네이션 억제) ▼▼
    condition_on_previous_text=False,      # 이전 텍스트 의존 제거 → 반복 루프 전파 차단(스트리밍 핵심)
    no_repeat_ngram_size=3,                # 동일 n-gram 반복 디코딩 금지 (ㄷㄷㄷ, 네네네 차단)
    repetition_penalty=1.1,                # 반복 토큰 확률 패널티
    compression_ratio_threshold=2.4,       # 네이티브 gzip 반복 탐지(긴 반복 대응)
    log_prob_threshold=-1.0,               # 저신뢰 세그먼트 모델 내부에서 드롭
    no_speech_threshold=0.6,               # 무음 구간 드롭 임계
    hallucination_silence_threshold=2.0,   # 무음 뒤 할루시네이션 의심 구간 스킵
)
```

**효과:** `ㄷㄷㄷ` 같은 반복은 디코딩 시점에 `no_repeat_ngram_size`/`repetition_penalty`로 생성 자체가 차단됨. `condition_on_previous_text=False`는 실시간 스트리밍에서 직전 청크의 잘못된 텍스트가 다음 청크로 번지는 것을 막아 특히 중요.

### Tier 2 — 후처리 반복 필터 강화 (Tier 1 우회분 방어)

`stt_engine.py` 최종 검증부에 **문자/토큰 단위 반복 탐지** 추가 (콤마 기반 검사 보완):

```python
def _is_repetitive(text: str) -> bool:
    t = text.strip().replace(" ", "")
    if len(t) < 4:
        return False
    # 1) 단일 문자 비율 (ㄷㄷㄷ, ㅋㅋㅋ, ...)
    most_common_ratio = max(t.count(c) for c in set(t)) / len(t)
    if most_common_ratio > 0.6:
        return True
    # 2) 고유 문자 다양성 (다른 글자가 거의 없음)
    if len(set(t)) / len(t) < 0.25:
        return True
    # 3) 2~4-gram 반복 (네네네, 그래그래그래)
    for n in (2, 3, 4):
        grams = [t[i:i+n] for i in range(0, len(t) - n + 1, n)]
        if len(grams) >= 3 and len(set(grams)) / len(grams) < 0.4:
            return True
    return False
```

- 단일 자모(`ㄷ`,`ㅋ`,`ㅎ`,`ㅠ` 등)만으로 이뤄진 세그먼트도 비유효 텍스트로 필터.
- 임계값은 모두 `config.py`로 노출하여 튜닝 가능하게.

### Tier 3 — 언어 감지 안정화 + 실시간 청크 품질 (설정 결정 필요)

후보 전략 (택1, 4절에서 컨펌 요청):
- **(가) 한국어 강제** — 회의 시스템 특성상 `language="ko"` 고정. 가장 안정적, 영어 혼용 정확도는 일부 하락.
- **(나) 자동 감지 + 폴백** — auto-detect하되 감지 확률 < 0.6이면 `ko`로 강제 재전사. 안정성/유연성 균형(권장).
- **(다) 현행 유지** — auto-detect 그대로 (Tier 1/2만 적용).

추가 검토 항목:
- 실시간 경로(`websocket.py`)에서 매우 짧은 청크에 `bilingual` initial_prompt가 오히려 할루시네이션을 유발할 수 있음 → 실시간에서는 prompt를 빼거나 짧게 하는 방안.
- VAD 트리거 청크가 너무 짧으면(예: <1초) 전사 스킵하는 최소 길이 가드.

---

## 4. 컨펌이 필요한 결정 사항

1. **언어 전략**: (가) 한국어 강제 / (나) 자동+폴백(권장) / (다) 현행 유지 — 어느 것?
2. **적용 범위**: Tier 1+2 먼저 적용 후 검증 → Tier 3 별도 진행 / 한 번에 전부?
3. **필터 공격성**: 실제 발화를 잃는 false-negative를 줄이려면 임계값을 보수적으로(놓치더라도 안전) vs 공격적으로(반복 확실히 제거).

---

## 5. 적용 후 검증 방법

- Docker 재기동 후 동일 시나리오 재현 → `ㄷㄷㄷ` 미출력 확인
- 정상 한국어 발화가 필터에 과도하게 걸리지 않는지(false drop) 로그 모니터링
- 실시간 레이턴시 영향 측정 (`no_repeat_ngram_size`/beam은 속도 영향 적음, 측정으로 확인)
- 기존 `pytest tests/` 회귀 통과

---

## 6. 변경 예정 파일

| 파일 | 변경 내용 |
|------|----------|
| `backend/app/core/stt_engine.py` | Tier 1 네이티브 파라미터, Tier 2 문자반복 필터 |
| `backend/app/config.py` | 신규 임계값 설정 노출 (no_repeat_ngram, repetition_penalty, 문자반복 비율 등) |
| `backend/app/api/v1/websocket.py` | (Tier 3 선택 시) 실시간 prompt/언어 전략, 최소청크 가드 |
```
