# 회의록 전체 기록 관리 개선 노트 (실시간 세션)

> 작성일: 2026-05-30
> 상태: **✅ Tier 1+2+3+4 구현 완료 · 영속성/재시작 생존 검증 OK** (권장안: SQLite+파일오디오)
> 제보: "최종 부분만 누적되고, 회의 시작~종료 전체가 기록 관리되지 않는다."

## ✅ 구현 완료 (2026-05-30)
- **Tier 1 (손실 차단)**: 종료 후처리가 누적 세그먼트(`finalized_segments`)를 **절대 []/마지막청크로 교체하지 않음**. 후처리/화자분리 실패해도 누적본 보존 후 `completed`.
- **Tier 2 (타임라인)**: `global_offset_sec` 도입 → 각 청크 전사 결과에 오프셋 가산하여 회의 시작~종료 **연속 타임라인**. (검증: 0-2/2-4/4-6 연속)
- **Tier 3 (전체 오디오·화자분리)**: 모든 청크를 `data/audio/{sid}.f32`에 **디스크 누적**(VAD 무관). 종료 시 전체 오디오로 화자분리 1회 → `assign_speakers()`로 **기존 세그먼트에 speaker만 매핑**(텍스트 보존). dead `diarization_audio_buffer` 제거. 세션 길이 상한(`MAX_SESSION_DURATION_SEC=4h`) 가드.
- **Tier 4 (영속성)**: stdlib `sqlite3` 기반 `app/db/store.py`(SessionStore). `session_manager`가 캐시+DB write-through(create/add_segment/update/edit) + 캐시미스 DB 폴백 + 시작 시 적재. 오디오는 파일, DB엔 메타+세그먼트+경로. `docker-compose`에 `./backend/data:/app/data` 볼륨, `.gitignore`에 `backend/data/`.
- **검증**: 누적 타임라인·화자매핑·DB 저장·**백엔드 재시작 후 API로 전체 회의록(3세그+화자) 복원**·목록/삭제 모두 정상. 신규 의존성 없음(stdlib).
- **미검증(사용자)**: 실제 마이크 스트리밍 end-to-end(브라우저 필요) — 개별 구성요소는 검증됨. 3~5분 실회의로 시작~종료 전체 보존·타임라인·화자 확인 권장.

---

## 0. 한 줄 요약

실시간 중에는 세그먼트가 정상 누적되지만(`add_segment`), **연결 종료 시 후처리가 누적된 전체 회의록을 "마지막 버퍼 1개 청크"의 재전사 결과로 덮어쓰거나(또는 빈 배열로) 교체**한다. 게다가 **전체 회의 오디오가 보존되지 않아**(매 청크마다 버퍼 clear) 종료 시 화자분리·재전사가 마지막 조각만 본다. 타임스탬프도 청크 로컬 기준이라 전체 타임라인이 끊긴다.

---

## 1. 데이터 흐름 추적 (현재 동작)

### (A) 실시간 스트리밍 중 — `backend/app/api/v1/websocket.py`
```
오디오 청크 수신 → AudioBufferProcessor.append_chunk() (sliding window, max 30s)
  → VAD 트리거(0.5s 무음 or 3s 연속) 시:
      save_audio_buffer_to_file(버퍼 전체) → Whisper 전사
      → "final" 메시지 전송
      → finalized_segments.append(seg)                # ① 메모리 리스트 누적
      → session_manager.add_segment(session_id, seg)  # ② 세션에 누적 (정상)
      → diarization_audio_buffer.append(버퍼.copy())   # ③ (실제로는 미사용; dead)
      → audio_processor.clear()                        # ④ ★버퍼 전체 비움★
```
- ②까지는 **세션에 전체가 누적**됨 → 실시간 화면엔 잘 쌓임.
- ④에서 매번 버퍼를 비우므로 **회의 전체 오디오는 어디에도 남지 않음**. ③은 append만 하고 종료 처리에서 읽지 않아 **죽은 코드**.

### (B) 연결 종료/중지 시 후처리 — 같은 파일 하단
```
full_audio = audio_processor.get_audio_data()   # ★마지막 clear 이후의 잔여 버퍼뿐★ (마지막 청크 or 빈값)

if full_audio 비어있음:
    update_session(segments=[])                 # ❌ (R2) 누적 세그먼트를 빈 배열로 덮어씀 → 전체 소실
elif len < 1초:
    update_session(segments=finalized_segments) # ✅ 유일하게 올바른 경로 (누적 유지)
else:  # >=1초
    whisper_results = transcribe(full_audio)     # ★마지막 청크만 재전사★
    diarization   = diarize(full_audio)          # ★마지막 청크만 화자분리★
    final_segments = align_segments(...)         # 마지막 청크 기준 결과
    if final_segments 비어있지 않음:
        update_session(segments=final_segments)  # ❌ (R1) 전체 회의록을 마지막 청크로 덮어씀
    else:
        final_segments = finalized_segments      # (폴백일 때만 누적 유지)
```

→ **결과**: 종료 시 잔여 버퍼 상태에 따라 세션의 `segments`가
(R2) 빈 배열, 또는 (R1) 마지막 청크만으로 **교체**됨. 사용자가 본 "최종 부분만" 증상과 정확히 일치.

---

## 2. 근본 원인 (정리)

| ID | 원인 | 위치 | 영향 |
|----|------|------|------|
| **R1** | 종료 후처리가 `update_session(segments=final_segments)`로 **누적본을 마지막 청크 재전사로 덮어씀** | websocket.py 종료부 else 분기 | 회의 대부분 소실, 마지막만 남음 |
| **R2** | 잔여 버퍼가 비면 `update_session(segments=[])`로 **전체 삭제** | websocket.py 종료부 빈값 분기 | 회의록 통째 소실 |
| **R3** | 스트리밍 중 `audio_processor.clear()`로 **전체 오디오 미보존**. `diarization_audio_buffer`는 append만 하고 미사용(dead) | websocket.py append/clear | 종료 시 화자분리·재전사가 마지막 청크만 처리 |
| **R4** | 각 청크를 독립 WAV로 전사 → **타임스탬프가 청크 로컬(0 기준)** | save_audio_buffer_to_file + 청크 전사 | 모든 세그먼트 start≈0, 시간 겹침 → 전체 타임라인/구간 정렬 불가 |
| **R5** | 세션이 **인메모리 dict + TTL 24h**, 디스크 영속성 없음 | session_manager.py | 서버 재시작 시 전체 기록 소실, 장기 보관 불가 |

> R1·R2가 "마지막만 남는" 직접 원인. R3·R4는 "전체 기준 화자분리/타임라인"이 애초에 불가능한 구조적 원인. R5는 기록 관리(보관/조회) 관점의 한계.

---

## 3. 개선 계획 (Tier)

### Tier 1 — 데이터 손실 즉시 차단 (최우선) ★
**원칙: 누적된 세션 세그먼트를 절대 비우거나 통째 교체하지 않는다.**
- 종료 후처리에서 `segments=[]` / `segments=final_segments(마지막청크)` 덮어쓰기 제거.
- 항상 `finalized_segments`(=전체 누적)를 기준 결과로 유지.
- 화자분리는 "기준 텍스트를 교체"하는 게 아니라 **기존 누적 세그먼트에 speaker 라벨만 입히는** 방향으로 변경(아래 Tier 3).
- 빈/짧은 버퍼여도 누적본 그대로 `completed` 처리.

### Tier 2 — 전체 타임라인 일관화 (R4)
- 세션 전역 경과시간 오프셋 `global_offset_sec` 도입.
- 매 청크 전사 결과의 `start/end`에 오프셋을 더해 **회의 시작~종료 연속 타임라인**으로 저장.
- 오프셋은 "지금까지 소비/누적한 오디오 총 길이"로 갱신(클리어 직전 버퍼 길이만큼 증가).
- 효과: 세그먼트가 시간순으로 정렬되고 겹치지 않음 → 회의록/내보내기/화자정렬 정상화.

### Tier 3 — 전체 오디오 보존 + 종료 시 1회 전체 화자분리 (R3)
- 스트리밍 중 들어오는 PCM을 **세션 단위로 계속 보존**:
  - 권장: **디스크에 증분 append**(세션 WAV 파일)로 메모리 폭증 방지. (예: `/tmp/session_{id}.f32` 또는 wav append)
  - 대안: 전용 메모리 누적 버퍼(별도, clear 안 함). 30분≈115MB/2시간≈460MB(82GB RAM 내 가능하나 디스크가 안전).
- 종료 시 보존된 **전체 오디오로 pyannote 1회 실행** → 전역 타임라인 기준으로 기존 누적 세그먼트에 `align_segments`(speaker만 매핑).
- `diarization_audio_buffer`(dead) 제거 또는 이 보존 버퍼로 대체.
- VRAM: 종료 후처리 1회성이라 Whisper와 동시 추론 회피(직렬화 유지).

### Tier 4 — 세션 영속성 (R5)
- 세션 결과(메타+세그먼트)와 오디오 파일을 **디스크에 영속화**. → **종합 검토는 §6 참조.**
- 인메모리 캐시는 그대로 두고 영속 계층(repository)만 추가.
- 범위가 커서 Tier 1~3 검증 후 별도 진행 권장.

---

## 4. 설계 상세 (구현 시)

### 4.1 종료 후처리 재설계 (핵심)
```
# 의사코드
base_segments = finalized_segments              # 항상 전체 누적이 기준
full_audio = session_audio (보존된 전체)         # Tier 3 보존 버퍼/파일
if full_audio 충분(>=1s) and diarization 가능:
    diar = diarize(full_audio)                   # 전체 1회
    base_segments = assign_speakers(base_segments, diar)  # 텍스트 유지, speaker만 갱신
update_session(status="completed",
               duration_sec=전체길이,
               speaker_count=고유화자수,
               segments=base_segments)           # 절대 [] / 마지막청크로 교체 금지
```
- `assign_speakers`: 기존 `align_segments`를 "whisper 텍스트 재생성" 대신 "세그먼트별 speaker 매핑"만 하도록 분리/추가.

### 4.2 전역 타임스탬프
- `global_offset_sec` 상태 추가. 청크 처리 직후 `global_offset_sec += 처리한_버퍼_길이초`.
- 세그먼트 생성 시 `start += offset_before`, `end += offset_before`.

### 4.3 전체 오디오 보존
- append_chunk 시 원본 PCM을 세션 파일에 append(또는 누적 리스트).
- 종료 시 그 파일로 duration/diarization. 종료 후 파일 정리(영속성 도입 시 보관).

### 변경 예정 파일
| 파일 | 변경 |
|------|------|
| `backend/app/api/v1/websocket.py` | 종료 후처리 덮어쓰기 제거, 전역 오프셋, 전체오디오 보존, dead buffer 제거 |
| `backend/app/core/pipeline.py` | `assign_speakers()`(텍스트 보존, speaker만 매핑) 분리 추가 |
| `backend/app/core/audio_processor.py` | (옵션) 전체 누적/오프셋 헬퍼 |
| `backend/app/services/session_manager.py` | (Tier 4) 디스크 영속화 |

---

## 5. 리스크 / 검증 방법
- **리스크**: 전체 오디오 보존 시 디스크/메모리 사용 증가 → 디스크 append + 종료 후 정리로 관리. 장시간 세션 상한(예: 3~4시간) 가드.
- **검증**:
  1. 3~5분 연속 발화 후 종료 → 세션 `segments`가 **처음부터 끝까지 전부** 남는지(개수/내용).
  2. 종료 직전 무음(빈 버퍼) 시에도 누적본 유지(R2 회귀).
  3. 마지막에 길게 말하고 종료 시 앞부분 보존(R1 회귀).
  4. 세그먼트 `start/end`가 시간순 증가·비겹침(R4).
  5. 화자 라벨이 전체 구간에 매핑(R3).
  6. (Tier4) 서버 재시작 후 조회 가능.

---

## 6. 저장소·DB 종합 검토 (Tier 4 상세)

### 6.1 현재 인프라 실태 (점검 결과, 2026-05-30)
| 항목 | 현황 | 함의 |
|------|------|------|
| 영속 계층 | **전무** — requirements에 DB 드라이버 0개, JSON 저장 코드도 없음 | 세션은 100% 인메모리 dict |
| 데이터 볼륨 | **없음** — docker-compose는 `./backend/models`(모델 가중치)만 마운트 | 컨테이너 재생성 시 데이터 소실 |
| 임시 오디오 | 컨테이너 `/tmp`(`tempfile.gettempdir()`), 처리 후 삭제 | 휘발성, 회의 원본 미보존 |
| 세션 GC | 인메모리 TTL 24h 후 삭제 | 영구 보관·이력·감사 불가 |
| 기존 Postgres `:5433` | **타 프로젝트 `youtube_shorts_db`** + LiteLLM 공용 | STT가 그대로 끼어 쓰면 안 됨(소유권/격리 문제) |
| 호스트 디스크 | `/home` 378GB 여유 | 오디오+DB 저장 여력 충분 |

> ⚠️ 핵심: 영속화를 도입하더라도 **데이터 볼륨을 마운트하지 않으면** `docker compose up --build`(소스가 이미지에 구워지는 구조 → 재빌드 필수)마다 데이터가 사라진다. **볼륨 마운트가 영속화의 전제 조건.**

### 6.2 무엇을 보존할 것인가 (데이터 분류)
| 데이터 | 성격 | 저장 위치(권장) |
|--------|------|----------------|
| 세션 메타(id, 상태, 생성시각, duration, 화자수, 언어) | 구조화·작음 | **DB** |
| 세그먼트(start/end/text/speaker/confidence/original_text/corrected) | 구조화·다수 | **DB**(세션 FK) |
| 회의 원본 오디오 | 대용량 바이너리 | **파일시스템**(볼륨), DB엔 경로만 |
| 내보내기 산출물(SRT/DOCX 등) | 파생·재생성 가능 | 생성 시점 on-the-fly(저장 불필요) 또는 파일 |

원칙: **오디오/대용량은 DB에 넣지 않고 파일시스템 + 경로 참조.** DB는 메타·세그먼트만.

### 6.3 저장소 선택지 비교
| 방식 | 장점 | 단점 | 적합성(본 프로젝트: 단일 노드·동시 3) |
|------|------|------|-----|
| **SQLite (볼륨 파일)** ★권장 | 서버 불필요, 단순, 백업=파일 복사, 온프레미스 단일박스에 최적 | 고동시성 약함(쓰기 직렬) | **매우 적합** (GPU 직렬화로 동시성 이미 제한적) |
| 전용 Postgres 컨테이너(신규, `stt` DB) | 동시성·확장성, 표준 | 운영요소 추가(컨테이너·자원) | 과함. 장기 다중사용자 확장 시 고려 |
| 기존 `:5433` pg에 **별도 DB `stt`** 추가 | 인프라 재활용 | 타 프로젝트와 동거(격리·권한·백업 얽힘) | 비권장(결합도↑) |
| JSON 파일(세션별) | 가장 단순 | 쿼리·동시쓰기·정합성 취약 | PoC용. 본격 비권장 |

→ **권장: SQLite + 파일시스템 오디오**, 모두 신규 데이터 볼륨에. (확장 필요 시 SQLAlchemy 추상화로 Postgres 전환 용이하게.)

### 6.4 스키마 초안 (SQLite/관계형)
```
sessions(
  session_id TEXT PK, status TEXT, created_at TIMESTAMP,
  duration_sec REAL, speaker_count INT, audio_language TEXT,
  audio_path TEXT, error_message TEXT
)
segments(
  id TEXT PK, session_id TEXT FK→sessions, seq INT,
  start REAL, end REAL, text TEXT, speaker TEXT,
  confidence REAL, no_speech_prob REAL,
  original_text TEXT, corrected INT, detected_language TEXT
)
-- index: segments(session_id, seq), sessions(created_at)
```

### 6.5 연결·운영 설계
- **드라이버**: 비동기 권장 — `aiosqlite`(SQLite) 또는 `asyncpg`(PG). 이벤트 루프 블로킹 방지. 추상화는 `SQLAlchemy 2.x(async)` 또는 경량 직접 쿼리.
- **연결 수명**: 모델 로딩처럼 `lifespan`에서 엔진/커넥션 1회 생성·종료. `dependencies.py`로 주입.
- **트랜잭션**: 세션 완료 시 메타+세그먼트 한 트랜잭션으로 flush. 실시간 누적은 (a) 메모리 유지 후 종료 시 일괄 저장(권장, 단순) 또는 (b) 세그먼트 증분 insert.
- **`session_manager` 역할 변경**: 인메모리 캐시 + **Repository(영속)** 이중화. `get_session`은 캐시 미스 시 DB 폴백. `update_session`/`add_segment`가 DB에도 반영.
- **마이그레이션**: 초기엔 `CREATE TABLE IF NOT EXISTS`로 충분. 스키마 진화 시 Alembic 도입.
- **백업/보존**: 볼륨 디렉터리 백업. 보존 정책(예: 90일) + 오디오 자동 삭제 옵션(메타는 유지).
- **보안/PII**: 회의 오디오·전사는 민감정보 → 볼륨 접근 권한, (선택) 저장 암호화, 보존기간 정책. 온프레미스라 외부 유출 위험은 낮음.

### 6.6 docker-compose 변경(필수)
```yaml
  backend:
    volumes:
      - ./backend/models:/app/models
      - ./backend/data:/app/data        # ← 신규: DB파일 + 오디오 저장 (영속)
```
- `LLM_*` 때와 마찬가지로 변경 후 **재빌드/재기동** 필요.
- `.gitignore`에 `backend/data/` 추가(오디오·DB 커밋 방지).

### 6.7 신규 의존성/파일
- requirements: `aiosqlite`(또는 `sqlalchemy[asyncio]`).
- 신규: `backend/app/db/` (엔진, 모델/스키마, repository), `session_manager` 수정.

---

## 7. 컨펌이 필요한 결정 사항
1. 적용 순서: **Tier 1+2+3 먼저(전체 기록 정상화) → Tier 4(영속성) 별도** vs 전부 한 번에?
2. 전체 오디오 보존 방식: **디스크 증분 append(권장)** vs 메모리 누적 버퍼?
3. **저장소 선택**: **SQLite + 파일시스템(권장)** / 전용 Postgres 신규 / 기존 :5433 재활용 / 보류?
4. **데이터 볼륨 추가**(`./backend/data:/app/data`) 동의? (영속화 전제 조건)
5. 보존 정책: 오디오·세션 보관 기간(예: 90일) / 무기한 / 오디오만 단기 삭제?
6. 장시간 세션 상한(예: 4시간) 설정값?
