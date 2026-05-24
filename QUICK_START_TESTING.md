# 빠른 테스트 가이드 - WebSocket 중복 연결 수정

## 🎯 목표
WebSocket 중복 연결 버그가 수정되었는지 확인

## ⚡ 빠른 테스트 (2분)

### 1단계: 브라우저 준비
```
Ctrl + F5  (캐시 완전 삭제)
F12        (개발자 도구)
```

### 2단계: 회의 시작
- "회의 시작" 버튼 클릭
- 콘솔에서 로그 확인

### 3단계: 확인 항목
```
✅ 예상 로그 (위에서 아래 순서로)
🎤 handleStart: 마이크 캡처 시작 중...
✅ handleStart: 마이크 캡처 성공
🔌 handleStart: WebSocket 연결 중...
✅ handleStart: WebSocket 연결 요청 완료
WebSocket connection established.      ← 딱 1번만 나타나야 함
📨 WebSocket 메시지 수신: info
```

### 4단계: 음성 테스트
```
마이크에 대고 말하기
→ 콘솔에서 계속 보이는지 확인:
🔊 오디오 청크 전송: 4096 샘플
🔊 오디오 청크 전송: 4096 샘플
```

### 5단계: 종료
```
"회의 종료" 클릭
→ WebSocket connection closed. (메시지 1번 나타남)
```

## ❌ 만약 문제가 보인다면?

### Q1: "WebSocket connection closed" 가 즉시 나타남
```
症状:
WebSocket connection established.
WebSocket connection closed.           ← 3초 이내
Attempting to reconnect...

원인: 다른 원인의 연결 오류 (서버 미실행, 포트 오류 등)
해결: docker-compose logs backend 확인
```

### Q2: "WebSocket이 이미 연결 중" 경고 반복
```
症状:
⚠️ WebSocket이 이미 연결 중입니다. 중복 연결 방지.

원인: 버튼을 빠르게 여러 번 클릭
해결: 한 번만 클릭, 또는 페이지 새로고침
```

### Q3: AudioWorklet 로드 실패
```
症状:
❌ AudioWorklet 로드 실패: ...

원인: /audio-processor.worklet.js 파일 누락
확인: 개발자 도구 → Network → 파일 요청 상태 확인
해결: npm run build 또는 서버 재시작
```

## 📊 성공 기준

| 항목 | 기준 | 확인 |
|------|------|------|
| 연결 횟수 | 1회 | "connection established" 1번만 |
| 연결 지속 | 30초+ | "connection closed" 의도하지 않게 나타나지 않음 |
| 오디오 전송 | 연속 | "오디오 청크 전송" 계속 나타남 |
| UI 업데이트 | 실시간 | 화면에 자막 표시 |

## 📚 상세 가이드
더 자세한 정보는 아래 파일 참고:
- `FIX_SUMMARY.md` - 상세 수정 설명
- `TESTING_GUIDE.md` - 전체 테스팅 가이드
- `CLAUDE.md` - 프로젝트 전체 기술 가이드

## 🔧 서버 상태 확인
```bash
# 백엔드 로그 확인
docker-compose logs -f backend | grep -E "connected|disconnected|session"

# 예상 출력 (단 1개의 session_id)
WebSocket client connected. Session: abc123...
Session created: abc123...
[음성 처리 로그들]
WebSocket session abc123... disconnected
```

---

**커밋 상태**: ✅ 수정완료 (commit 4da69058)
