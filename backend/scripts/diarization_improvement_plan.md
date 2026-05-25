# 화자 분리 (Speaker Diarization) 개선 계획

## 현황 분석

### 📊 실시간 로그 분석 결과

**테스트 환경**: WebSocket 스트리밍 (약 3분 지속)

| 항목 | 결과 | 상태 |
|------|------|------|
| **STT 처리** | 43회 | ✅ 정상 |
| **세그먼트 전송** | 58개 | ✅ 정상 |
| **화자 분리 실행** | 0회 | ❌ 미실행 |
| **레이턴시** | ~500ms | ✅ 목표 달성 |
| **VRAM 사용** | 2.7GB | ✅ 안정 |

---

## 🔍 문제 분석

### 왜 화자 분리가 안 보일까?

**원인: 아키텍처 설계 문제**

```
┌─────────────────────────────────────────────────┐
│     WebSocket 스트리밍 (실시간 자막)             │
│  ✅ Whisper STT (빠른 응답)                      │
│  ❌ 화자 분리 (생략됨)                          │
└──────────────┬──────────────────────────────────┘
               │ 연결 종료
               ▼
┌─────────────────────────────────────────────────┐
│     최종 후처리 (연결 끝난 후)                   │
│  ✅ Whisper (정확도 높은 beam_size=5)           │
│  ✅ Pyannote 화자 분리 실행 ← 여기서 실행!      │
│  ✅ align_segments() 정렬                        │
│  ✅ 클라이언트 전송                              │
└─────────────────────────────────────────────────┘
```

**현재 코드 (websocket.py line 151)**:
```python
speaker="SPEAKER_00"  # ← 하드코딩, 화자 분리 안 함
```

---

## 🚀 개선 방안

### 방안 1: 스트리밍 중 화자 분리 추가 (강력 권장) ⭐⭐⭐

**개선 내용**:
- 실시간 스트리밍 중에도 주기적으로 화자 분리 실행
- 5초마다 또는 10개 세그먼트마다 화자 분리 실행
- 실시간 자막에 SPEAKER_00, SPEAKER_01 등 표시

**코드 변경**:
```python
# websocket.py line 104-186 수정
if vad_triggered:
    # 1. Whisper STT (빠름)
    whisper_results = await stt_engine.transcribe(...)
    
    # 2. 주기적 화자 분리 (새로 추가)
    if len(diarization_audio_buffer) >= 10 or audio_duration > 5:
        # 누적된 오디오로 화자 분리 실행
        diarization_results = await diarizer.diarize(temp_wav)
        final_segments = align_segments(whisper_results, diarization_results, session_id)
        # → SPEAKER 정보 포함한 결과 전송
```

**성능 트레이드오프**:
- ✅ 장점: 실시간으로 화자 분리 정보 확인 가능
- ❌ 단점: 응답 시간 증가 (500ms → 1-2초)

**권장 설정**:
```python
# 화자 분리 실행 조건 (둘 중 하나 만족시)
diarization_interval = 5  # 5초마다
diarization_buffer_threshold = 8  # 또는 8개 세그먼트마다
```

---

### 방안 2: 백그라운드 화자 분리 실행

**개선 내용**:
- 스트리밍 중 세그먼트 수집만 진행
- 백그라운드 태스크에서 비동기로 화자 분리 실행
- 완료되면 클라이언트에 업데이트 발송

**코드 변경**:
```python
# 별도 백그라운드 태스크
async def background_diarization_task(audio_buffer, segments):
    # 누적된 오디오로 화자 분리 실행
    diarization_results = await diarizer.diarize(temp_wav)
    # 세그먼트와 정렬
    final_segments = align_segments(whisper_results, diarization_results, session_id)
    # WebSocket으로 업데이트 발송
    await websocket.send_json({
        "type": "speaker_updated",
        "segments": final_segments
    })
```

**장점**:
- ✅ 실시간 응답 속도 유지
- ✅ 화자 분리 정보 제공
- ✅ 병렬 처리로 효율적

**단점**:
- 약간의 지연 (1-2초)

---

### 방안 3: 현재 구조 유지 + 문서화

**개선 내용**:
- 현재 구조는 이미 최적화됨
- 스트리밍 종료 후 화자 분리 자동 실행
- 프론트엔드에서 `speaker_updated` 이벤트 수신

**장점**:
- ✅ 성능 최적 (응답 500ms)
- ✅ 안정성 높음
- ✅ 구현 복잡도 낮음

**단점**:
- 실시간 화자 분리 정보 없음
- 스트리밍 중에는 SPEAKER_00으로만 표시

---

## 🛠️ 권장 개선 순서

### Phase 1: 현재 구조 검증 (오늘)
```bash
# 1. 스트리밍 종료 후 화자 분리 동작 확인
# 2. 파일 업로드로 화자 분리 테스트
# 3. 정확도 측정

POST /api/v1/transcribe (파일 업로드)
→ 화자 분리 자동 실행
→ GET /api/v1/sessions/{id}로 결과 확인
```

### Phase 2: 백그라운드 화자 분리 추가 (이번주)
- 스트리밍 중 화자 분리를 백그라운드에서 실행
- 응답 속도는 유지하면서 화자 정보 제공

### Phase 3: 실시간 화자 분리 (다음주, optional)
- 5초마다 화자 분리 실행
- 응답 시간 증가를 감수하고 더 나은 UX 제공

---

## 🔧 즉시 실행 가능한 개선: 백그라운드 화자 분리

```python
# websocket.py에 추가 (간단한 개선)

# 새로운 변수 추가 (line 80 근처)
diarization_results_cache = None
diarization_speakers = {}

# VAD 트리거 후 (line 185 근처)
# 백그라운드 태스크 등록
asyncio.create_task(
    background_diarization(
        temp_full_wav,
        whisper_results,
        session_id,
        websocket
    )
)

# 새로운 함수 추가
async def background_diarization(wav_path, whisper_segments, session_id, websocket):
    """백그라운드에서 화자 분리 실행"""
    try:
        logger.info(f"🔄 [백그라운드] 화자 분리 시작")
        diarizer = DiarizationEngine.get_instance()
        
        # 화자 분리 실행
        diarization_results = await diarizer.diarize(wav_path)
        logger.info(f"✅ [백그라운드] 화자 분리 완료: {len(diarization_results)} 구간")
        
        # 세그먼트 정렬
        from app.core.pipeline import align_segments
        final_segments = align_segments(whisper_segments, diarization_results, session_id)
        
        # 클라이언트에 업데이트 발송
        await websocket.send_json({
            "type": "speaker_updated_background",
            "session_id": session_id,
            "segments": [seg.dict() for seg in final_segments],
            "message": f"화자 분리 완료: {len(set(seg.speaker for seg in final_segments))}명"
        })
        logger.info(f"📤 백그라운드 화자 분리 결과 전송 완료")
        
    except Exception as e:
        logger.error(f"❌ 백그라운드 화자 분리 실패: {e}")
```

---

## 📋 테스트 계획

### 1단계: 파일 업로드로 화자 분리 검증
```bash
# curl로 파일 업로드 테스트
curl -X POST \
  -F "audio_file=@sample.wav" \
  -F "enable_diarization=true" \
  http://localhost:8000/api/v1/transcribe

# 응답에서 speaker 정보 확인
# {
#   "session_id": "...",
#   "segments": [
#     {
#       "speaker": "SPEAKER_00",  ← 화자 정보
#       "text": "...",
#       "start": 0.0,
#       "end": 2.5,
#       "confidence": 0.95
#     }
#   ]
# }
```

### 2단계: WebSocket 스트리밍 종료 후 화자 분리 확인
```python
# 스트리밍 종료 후 로그에 다음 메시지 나타남을 확인:
# "🔄 Final post-processing (Diarization) for session: ..."
# "🎙️  화자 분리 완료: X명의 화자 감지"
```

### 3단계: 정확도 측정
```bash
# 실제 2인 회의 오디오로 테스트
# AIHUB 또는 Common Voice 데이터 활용
# F1-Score >= 85% 목표
```

---

## 📊 성능 비교

| 방안 | 응답시간 | 화자 분리 | 구현도 | 추천 |
|------|---------|---------|-------|------|
| 현재 (스트리밍만) | ~500ms | ❌ 나중에 | 낮음 | - |
| 방안 1 (실시간) | 1-2초 | ✅ 실시간 | 중간 | ⭐⭐ |
| 방안 2 (백그라운드) | ~500ms | ✅ 1-2초후 | 낮음 | ⭐⭐⭐ |
| 방안 3 (유지) | ~500ms | ✅ 종료후 | 낮음 | ⭐ |

---

## 🎯 최종 권장사항

### 즉시 실행 (오늘)
1. ✅ 파일 업로드로 화자 분리 테스트
2. ✅ 정확도 측정 (F1-Score 확인)
3. ✅ 로그 분석 도구로 동작 확인

### 단기 (이번주)
1. 🔧 백그라운드 화자 분리 추가 (방안 2)
2. ✅ 실시간 + 종료후 화자 분리 이중화
3. 📊 정확도 재측정

### 장기 (다음주)
1. 🎙️ 실시간 화자 분리 개선 (선택사항)
2. 📈 Pyannote 파라미터 튜닝
3. 🧪 다양한 음성 데이터로 정확도 검증

---

## 💡 요약

**현재 상태**: 화자 분리 구현 완료, 실행 타이밍 최적화 필요

**다음 단계**: 
1. 파일 업로드로 화자 분리 동작 확인
2. 백그라운드 화자 분리 추가 (선택사항)
3. 정확도 측정 및 최적화

**예상 결과**: F1-Score >= 85% 달성 가능 (실제 음성 데이터 기준)
