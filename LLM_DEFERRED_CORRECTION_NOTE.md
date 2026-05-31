# LLM 보정 지연(Deferred) 처리 개선 노트

> 작성일: 2026-05-30
> 상태: **✅ Option A / Phase 1 구현 완료 (지연 30초) · 제어흐름 검증 OK**
> 제보/아이디어: 실시간 LLM 보정 때문에 지연이 있다. → **STT는 즉시 화면 출력**하고, LLM 보정은 **약 30초 이격을 두고 후속 배치**로 처리하자.

## ✅ 구현 완료 (2026-05-30) — 지연 30초
- **config**: `LLM_CORRECTION_MODE=deferred`(기본; realtime|off 롤백 가능), `LLM_DEFER_SECONDS=30`, `LLM_SWEEP_INTERVAL=5`, `LLM_BATCH_SIZE=5`.
- **websocket.py**: 저신뢰 세그먼트를 즉시 보정하지 않고 `pending_corrections` 큐에 적재. 세션당 `_correction_worker`가 5초마다 깨어 **확정 후 30초 경과분**을 최대 5개씩 보정→`corrected` 전송. 명시적 `stop` 시 `_flush_pending_corrections()`로 잔여 전량 보정 후 화자분리/완료저장. 단순 끊김 시 워커 취소+대기분 폐기(누적 세그먼트는 영속). Phase 1 = 개별 호출.
- **프런트**: 변경 없음(이미 `corrected` 처리, 30초 늦게 도착).
- **검증**: 연결 시 `🕒 지연 보정 모드: 30초 후속 배치` 워커 기동, stop→flush→완료 경로 정상(오류 없음). 실제 보정 품질/지연은 실음성 회의로 확인 권장.
- **미구현(선택)**: Phase 2 진짜 배치(1콜 다세그먼트), Phase 3 GPU 양보.

---

## 0. 한 줄 요약

보정을 "세그먼트 확정 즉시"가 아니라 **"확정 후 ~30초 뒤에 모아서(batch) 후속 처리"** 로 바꾼다. STT 자막은 지연 없이 즉시 표시되고, 보정 결과는 잠시 뒤 `corrected` 메시지로 조용히 반영된다. GPU(Whisper↔LLM) 경쟁 스파이크도 분산된다.

---

## 1. 현재 동작과 문제

### 현재 (`websocket.py`, `llm_corrector.py`)
- 저신뢰 세그먼트가 확정되면 **즉시** `asyncio.create_task(_correct_in_background(seg, prev))` 로 LLM 호출(논블로킹).
- 이미 수신 루프는 막지 않지만(이전 개선), 다음 문제가 남음:
  1. **GPU 경쟁**: gemma(LLM, host:8080)와 Whisper/pyannote가 동일 GPU 경쟁 → 보정이 도는 동안 **STT 추론 자체가 느려짐**(VRAM ~9.5GB 관측). 체감 지연의 핵심.
  2. **호출 빈도**: 발화가 잦으면 세그먼트마다 LLM 호출(각 ~5.5s)이 몰려 큐가 쌓임(`max_workers=2`).
  3. **즉시성 불필요**: 보정 결과는 회의 가독성용이라 수십 초 늦어도 무방. 즉시 처리할 이유가 약함.

### 목표
- STT 자막: **지연 0**(현재처럼 즉시 `final` 표시).
- LLM 보정: **확정 후 ~30초 뒤** 모아서 처리 → GPU 한가한 구간에 배치 실행 → `corrected`로 교체.

---

## 2. 설계 방안 비교

| 방안 | 내용 | 장단점 |
|------|------|--------|
| **A. 주기적 지연 스윕(배치)** ★권장 | 저신뢰 세그먼트를 "보정 대기 큐"에 적재만. 백그라운드 워커가 N초(예 5s)마다 깨어 **확정 후 ≥30초 지난** 대기 세그먼트를 모아 보정 | 즉시성 분리 + 배치로 호출 수↓ + GPU 스파이크 분산. 구현 중간 |
| B. 세그먼트별 지연 태스크 | 세그먼트마다 `sleep(30)` 후 보정 | 단순하나 타이머 다수, 배치 이점 없음 |
| C. 종료 시 일괄만 | 회의 중 보정 안 하고 종료 후 전체 보정 | 가장 단순·지연 0이나, **회의 중에는 보정 안 보임**(아이디어의 "30초 후속"과 불일치) |

→ **A 채택**: "30초 이격 후속" 요구에 정확히 부합하고 GPU 부담도 가장 잘 분산.

---

## 3. 상세 설계 (Option A)

### 3.1 보정 대기 큐 + 지연 스윕
```
pending = []   # [(segment, prev_texts, finalized_at_ts)]

# 세그먼트 확정 시: 즉시 호출 대신 큐에 적재만
if corrector.should_correct(seg.confidence, seg.text):
    pending.append((seg, prev_texts, time.monotonic()))

# 백그라운드 워커(세션당 1개):
async def correction_worker():
    while not stopped:
        await asyncio.sleep(SWEEP_INTERVAL)   # 예: 5초
        now = time.monotonic()
        due = [p for p in pending if now - p.ts >= LLM_DEFER_SECONDS]  # 30초 경과분
        if due:
            await correct_batch(due)           # 모아서 보정 → corrected 전송
            remove due from pending
```
- **지연**: `LLM_DEFER_SECONDS=30` 경과한 것만 처리 → "30초 이격" 충족.
- **스윕 간격**: `SWEEP_INTERVAL=5s` 정도(정확히 30초일 필요 없음, 30~35초 사이 처리).
- 워커는 세션당 1개 `asyncio.create_task`로 생성, 종료 시 취소+flush.

### 3.2 배치 보정 (호출 수↓)
- 한 번에 최대 `LLM_BATCH_SIZE`(예: 5) 세그먼트를 처리.
- **방식 선택지**:
  - (b1) **개별 호출, 직렬**: 큐의 due 세그먼트를 순차 보정(현 `correct_async` 재사용). 안전·단순. 호출 수는 그대로지만 한가한 구간에 몰아 실행 → GPU 스파이크 분산. **1차 권장**.
  - (b2) **진짜 배치(1콜 다세그먼트)**: 여러 문장을 한 프롬프트에 넣고 JSON 배열로 교정 반환. 호출 수 대폭↓이나 정렬/파싱 오류 위험 → 견고한 파싱+세그먼트별 길이가드+실패시 원문. **2차(선택)**.
- 과교정 방지(기존 가드 유지): 자모/garbage·초단문 제외, 길이비율 가드, 실패 시 원문.

### 3.3 종료/끊김 처리
- **명시적 종료(stop)**: 화자분리 전에 **대기 큐 전체를 즉시 flush**(지연 무시하고 남은 것 모두 보정) → 최종 저장에 반영.
- **단순 끊김(재연결 대기)**: 워커 취소, 대기 큐는 버리거나 세션에 보존(재연결 시 미보정 세그먼트는 다음 스윕이 처리하도록 재적재 가능 — 단순화하려면 종료 시에만 flush).
- 보정 결과는 항상 `finalized_segments`의 세그먼트 객체를 in-place 수정(참조) → 최종 저장 일관.

### 3.4 GPU 경쟁 완화(부가)
- 배치 보정 직전, 직전 STT 추론 종료 후 잠깐(예: 0.5s) 양보 → STT 우선. (선택)
- 동시 보정 동시성은 `max_workers` 1~2 유지.

### 변경 예정 파일
| 파일 | 변경 |
|------|------|
| `backend/app/api/v1/websocket.py` | 즉시 create_task 제거 → 대기 큐 적재. 세션당 `correction_worker` 태스크 추가. stop 시 flush, 끊김 시 취소 |
| `backend/app/core/llm_corrector.py` | (b2 채택 시) `correct_batch()` 추가. 아니면 그대로 재사용 |
| `backend/app/config.py` | `LLM_CORRECTION_MODE`(realtime\|deferred\|off), `LLM_DEFER_SECONDS=30`, `LLM_SWEEP_INTERVAL=5`, `LLM_BATCH_SIZE=5` |

---

## 4. 설정(config) 초안
```python
LLM_CORRECTION_MODE: str = "deferred"   # realtime | deferred | off
LLM_DEFER_SECONDS: float = 30.0         # 확정 후 이 시간 경과분만 보정
LLM_SWEEP_INTERVAL: float = 5.0         # 대기 큐 점검 주기(초)
LLM_BATCH_SIZE: int = 5                 # 1회 스윕 최대 처리 세그먼트 수
# (기존 유지) LLM_CONFIDENCE_GATE, LLM_CONTEXT_WINDOW, LLM_MAX_LEN_RATIO ...
```
- `realtime`(기존)·`off`도 남겨 즉시 롤백/비교 가능.

---

## 5. 프런트엔드 영향
- **거의 없음**: 이미 `corrected` 메시지로 텍스트 교체 + `✨ AI 보정` 배지 처리 중. 보정이 ~30초 늦게 도착할 뿐.
- (선택) 보정 예정 세그먼트에 옅은 "보정 대기" 표시를 줄 수도 있으나 필수 아님.

---

## 6. 리스크 / 검증
- **리스크**: 종료 직후 flush 양이 많으면 종료 처리 지연 → 배치+상한으로 관리. 재연결 중 대기분 처리 정책(단순화: 종료 flush). b2 배치 파싱 오류 → 견고 파싱+원문 폴백.
- **검증**:
  1. 실시간 자막이 보정과 무관하게 **즉시** 표시(지연 0) 확인.
  2. 약 30초 뒤 `corrected` 메시지가 도착해 텍스트 교체 확인.
  3. 보정 구동 중 STT 처리시간/체감 지연이 기존 대비 감소(로그의 ⏱️ 처리시간 비교).
  4. 종료 시 미보정 대기분이 flush되어 최종 저장에 반영.
  5. `LLM_CORRECTION_MODE=off`로 즉시 비활성/롤백 가능.

---

## 7. 단계별 계획
- **Phase 1**: 대기 큐 + 지연 스윕(개별 호출 b1) + config + stop flush. (핵심, 즉시 효과)
- **Phase 2**(선택): 진짜 배치 호출(b2)로 호출 수 추가 절감.
- **Phase 3**(선택): GPU 양보/우선순위 미세조정.

---

## 8. 컨펌이 필요한 결정 사항
1. 방안: **A(주기적 지연 스윕)** 진행? (권장)
2. 지연 시간 `LLM_DEFER_SECONDS`=30초로 OK? (조정 가능)
3. 배치 방식: **Phase 1은 개별 호출(b1, 안전)** 로 시작 → 효과 보고 b2 검토, 동의?
4. 재연결 중 미보정 대기분: **종료 시 일괄 flush**로 단순화 OK? (아니면 재연결 이어받아 처리)
