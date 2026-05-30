# 회의 세션 분절(청크 단위 세션) 개선 노트

> 작성일: 2026-05-30
> 상태: **✅ Option A 구현 완료 · 재연결 이어쓰기/단일 세션 E2E 검증 OK**
> 제보: `/sessions`에서 하나의 회의가 청크 단위로 나뉘어 여러 세션으로 관리됨.

## ✅ 구현 완료 (2026-05-30) — Option A
- **프런트(`SessionContext.tsx`)**: 회의 단위 `meetingIdRef`(uuid) 1회 생성, 재연결에도 유지. WS URL에 `?session_id=<meetingId>` 전달. `clearSession`에서만 초기화(다음 회의=새 ID). `disconnect`(회의 종료)에서 `{command:"stop"}` 전송 후 종료.
- **백엔드(`websocket.py`)**: `websocket.query_params`에서 세션 ID 수용. 기존(미완료) 세션이면 **resume**(누적 세그먼트 복원 + 보존 오디오 파일 크기로 `global_offset_sec` 복원 → 타임라인 연속, 오디오 파일 이어붙이기). **명시적 `stop`일 때만** 화자분리+`completed`; 단순 끊김은 후처리 생략하고 `processing` 유지(재연결 대기). 연결마다 `conn_nonce`로 세그먼트 ID 충돌 방지. `_active_ws_sessions`로 동일 세션 동시연결 거부.
- **고아 세션 GC(`session_manager.py`)**: stop 없이 버려져 `processing`에 멈춘 세션을 (생성 후 상한+1h 경과 시) 자동 `completed` 처리.
- **검증(E2E)**: 같은 meetingId로 끊김→재연결→stop 시나리오에서 **세션 1개만 유지**(분절 없음), 끊김 시 `processing` 유지, stop 시 `completed`. 로그 `♻️ Session resumed` / `⏸️ 연결 끊김(재연결 대기)` / `🔄 Final post-processing` 확인.
- **미검증(사용자)**: 실제 마이크로 회의 중 네트워크 끊김→재연결 시 타임라인 연속·세그먼트 이어짐 확인 권장. 기존에 쌓인 분절 세션은 §4(정리) 필요 시 별도 처리.

---

## 0. 한 줄 요약

**세션 = "WebSocket 연결 1회"** 로 묶여 있고, 프런트엔드가 끊기면 **자동 재연결(최대 5회)** 하면서 연결마다 **새 `session_id`** 가 생성된다. 그 결과 **한 회의 = 연결 횟수만큼의 세션**으로 분절된다. 해결책은 **세션 = "회의 1회"** 가 되도록, 클라이언트가 회의 단위의 안정적 ID를 소유하고 재연결 시 같은 세션을 **이어쓰기(resume)** 하는 것.

---

## 1. 원인 분석 (코드 추적)

### R1. 연결마다 새 세션 생성 (백엔드)
`backend/app/api/v1/websocket.py`
```python
@router.websocket("/ws/stream")
async def websocket_stt_stream(websocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())     # ← 연결될 때마다 무조건 새 ID
    session_manager.create_session(session_id)
```
- 클라이언트가 세션 ID를 지정할 방법이 없음. 연결 = 세션.

### R2. 자동 재연결이 새 연결(=새 세션)을 만듦 (프런트엔드)
`frontend/src/context/SessionContext.tsx`
```python
ws.onclose = () => {
   if (reconnectCountRef.current < 5) {      # 최대 5회 지수 백오프 재연결
       ... connect(url)                       # ← 새 WebSocket → 새 session_id
   }
}
```
- 네트워크 블립/일시 끊김마다 재연결 → 매번 새 세션. 회의 중 N번 끊기면 N+1개 세션.

### R3. 끊길 때마다 "종료 후처리"가 실행되어 각 조각이 완료 저장됨
- WS 종료(정상/비정상 구분 없음) 시 화자분리+`status=completed`로 저장 → 각 조각이 독립 "완료 회의"로 `/sessions`에 노출.
- 즉 재연결로 끊긴 앞 조각도 별도 완료 세션이 됨.

> 정리: **R1(연결=세션) × R2(잦은 재연결) × R3(끊길 때마다 완료저장)** → 한 회의가 청크 세션으로 분절.

---

## 2. 개선 방안

### ✅ 권장: Option A — "회의 단위 세션" + 재연결 이어쓰기(resume)
클라이언트가 회의 시작 시 **meetingId(안정적 uuid)** 를 1회 생성하고, 모든 (재)연결에서 동일 ID를 백엔드에 전달. 백엔드는 같은 ID면 **새로 만들지 않고 이어쓰기**.

1. **프런트엔드**
   - `startRecording`(회의 시작)에서 `meetingId` 1회 생성 → 재연결에도 **유지**(회의 종료 시에만 초기화).
   - WS URL에 전달: `ws://host:8000/api/v1/ws/stream?session_id=<meetingId>`.
   - 회의 종료(`handleStop`)에서만 `{command:"stop"}` 전송 후 재연결 차단하고 종료.

2. **백엔드 `/ws/stream`**
   - `session_id = websocket.query_params.get("session_id") or uuid4()`.
   - 기존 세션이면 **resume**: 
     - `finalized_segments ← session.segments` (기존 누적 복원)
     - `global_offset_sec ← 보존 오디오 길이`(`data/audio/{id}.f32` 파일 크기/4/16000) → 타임라인 연속 유지
     - 세션 오디오 파일은 같은 경로라 **append 계속**(이미 id 기반) → 전체 오디오 보존 유지
     - `status="processing"`
   - **종료 트리거 구분**:
     - 명시적 `stop` 커맨드 → 화자분리 + `completed` 저장 (회의 진짜 종료).
     - 단순 연결 끊김(재연결 예상) → **finalize 안 함**. 누적분만 보존(`processing` 유지). 재연결로 이어감.
   - 동일 `session_id` 동시 연결 방지(중복 accept 거부 또는 이전 연결 정리).

3. **효과**: 재연결·일시 끊김이 있어도 **한 회의 = 한 세션**. 타임라인/오디오/세그먼트가 끊김 없이 누적.

### 대안 비교
| 방안 | 내용 | 장단점 |
|------|------|--------|
| **A. 회의 세션 + resume** ★ | 클라 meetingId + 백엔드 이어쓰기 + stop에서만 완료 | 근본 해결. 구현 중간 |
| B. 재연결 시 같은 id 재사용만 | meetingId 전달 + create 시 기존이면 덮어쓰기 방지 | A의 부분집합. resume/finalize 구분 없으면 R3 잔존 |
| C. 재연결 비활성/축소 | onclose 자동재연결 끔 | 끊기면 회의 유실 위험. 비권장 |
| D. UI 병합만 | 목록에서 meetingId로 그룹화 | 근본 미해결, 데이터는 여전히 분절 |

---

## 3. 설계 상세 (Option A, 구현 시)

### 3.1 종료 트리거 구분 (핵심)
현재는 WS가 끊기면 무조건 후처리·완료. 변경:
```
while True: receive...
  if text command == "stop":
      finalize = True; break          # 명시적 종료
except WebSocketDisconnect:
      finalize = False                 # 비정상/재연결 → finalize 안 함

# 루프 종료 후
if finalize:
    <전체 오디오 화자분리 + completed 저장 + speaker_updated 전송>
else:
    logger.info("연결 끊김(재연결 대기) → 누적분 보존, 미완료 유지")
    # status는 processing 유지 (이미 add_segment로 누적 영속됨)
```

### 3.2 resume 시 상태 복원
```
existing = session_manager.get_session(session_id)
if existing and existing.status != "completed":
    finalized_segments = list(existing.segments)
    global_offset_sec = os.path.getsize(audio_path)/4/16000 if exists else (max end of segments)
    logger.info(f"♻️ 세션 이어쓰기: {len(finalized_segments)}개 세그먼트, offset={global_offset_sec:.1f}s")
else:
    session_manager.create_session(session_id)
    finalized_segments = []; global_offset_sec = 0.0
```
- 세그먼트 id 중복 방지: resume 후 `processing_count`를 기존 최대치+1에서 시작하거나 uuid 기반 id 사용.

### 3.3 미완료 세션 정리(고아 세션)
- stop 없이 영영 안 돌아오는 세션 대비: GC가 일정 시간(예: 30분) 이상 `processing`이고 더 이상 활동 없으면 자동 finalize 또는 `completed` 마감.

### 변경 예정 파일
| 파일 | 변경 |
|------|------|
| `frontend/src/context/SessionContext.tsx` | meetingId 생성·유지, WS URL에 `?session_id=`, 종료 시에만 reset |
| `frontend/src/app/page.tsx` | 회의 시작/종료와 meetingId 수명 연결 |
| `backend/app/api/v1/websocket.py` | query_params 세션 ID 수용, resume 상태복원, stop/끊김 finalize 구분, 동시연결 가드 |
| `backend/app/services/session_manager.py` | (옵션) 고아 `processing` 세션 자동 마감 GC |

---

## 4. 기존 분절 데이터 정리(마이그레이션)
- 이미 쌓인 청크 세션들: (a) 짧은(예: 세그먼트 1~2개 또는 duration<몇 초) 세션 일괄 삭제 옵션, 또는 (b) 그대로 두고 신규부터 정상화.
- `/sessions` 목록에 "처리중/완료" 상태·세그먼트 수 표시해 식별 쉽게.

---

## 5. 리스크 / 검증
- **리스크**: resume 중 동일 세션 동시 연결, 세그먼트 id 충돌 → 가드 필요. stop 누락 시 고아 세션 → GC 마감.
- **검증**:
  1. 회의 중 강제로 네트워크 끊었다 재연결 → `/sessions`에 **세션 1개만** 유지, 세그먼트 이어짐.
  2. 타임라인이 재연결 경계에서 연속(겹침/리셋 없음).
  3. 명시적 "회의 종료" 시에만 `completed` + 화자분리 1회.
  4. 보존 오디오(.f32)가 재연결 후에도 이어붙어 전체 길이 일치.

---

## 6. 컨펌이 필요한 결정 사항
1. 방안: **Option A(회의 세션 + resume)** 진행? (권장)
2. 종료 정의: **명시적 "회의 종료" 버튼에서만 완료** 처리(끊김은 이어쓰기)로 OK?
3. 고아 `processing` 세션 자동 마감 시간(예: 30분 무활동)?
4. 기존 분절 세션: 일괄 정리 vs 보존(신규부터 정상화)?
