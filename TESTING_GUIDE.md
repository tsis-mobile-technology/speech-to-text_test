# WebSocket 중복 연결 수정 - 테스트 검증 가이드

## 문제점 (수정 완료)
- WebSocket이 여러 번 동시에 연결되어 즉시 끊김
- 회의 시작 후 음성이 전송되지 않음
- 백엔드 로그에 3개 이상의 서로 다른 session_id가 나타남

## 적용된 수정사항

### 1. Frontend - useWebSocket.ts
✅ `connect()` 함수에서 중복 연결 방지
- CONNECTING 상태: 새 연결 시도 시 조기 반환
- OPEN 상태: 기존 연결을 먼저 닫고 새 연결 시도

### 2. Frontend - page.tsx
✅ handleStart 함수 순서 수정
- `await startRecording()` 완료 후에 `wsConnect()` 호출
- 마이크 권한 확인 먼저 진행

### 3. Frontend - useAudioCapture.ts
✅ AudioWorklet 로딩 강화
- try/catch로 로드 실패 명확하게 처리
- 청크 수신 추적 (매 10개마다 로그)

### 4. Backend - websocket.py
✅ 상세 로깅 추가
- 연결 생성, 세션 생성, 엔진 초기화 각 단계 로그

## 테스트 절차

### 준비 단계
```bash
# 브라우저 캐시 완전 삭제
Ctrl + F5  (또는 Command + Shift + R on Mac)

# 개발자 도구 열기
F12

# Console 탭 선택
```

### 테스트 실행
1. "회의 시작" 버튼 클릭
2. 3-5초 대기
3. 콘솔 로그 확인
4. 음성 입력 테스트

## 예상 콘솔 로그 순서

```
🎤 handleStart: 마이크 캡처 시작 중...
📦 AudioWorklet 로드 중: /audio-processor.worklet.js
✅ AudioWorklet 로드 성공
✅ MediaStreamAudioSourceNode 생성 성공
✅ AudioWorkletNode 생성 성공
✅ handleStart: 마이크 캡처 성공

🔌 handleStart: WebSocket 연결 중...
🔌 WebSocket 연결 시도: ws://localhost:8000/api/v1/ws/stream
✅ handleStart: WebSocket 연결 요청 완료

WebSocket connection established.
📨 WebSocket 메시지 수신: info    ← 서버 환영 메시지

[말하기 시작]
🔊 오디오 청크 전송: 4096 샘플
🔊 오디오 청크 전송: 4096 샘플
...
```

## 검증 항목

### ✅ 필수 확인사항
- [ ] "WebSocket connection established"가 **1번만** 나타남
- [ ] "WebSocket connection closed"가 3초 이내에 나타나지 않음 (음성 중단 전까지)
- [ ] "🔊 오디오 청크 전송" 메시지가 연속으로 나타남
- [ ] "📨 WebSocket 메시지 수신: info" 메시지가 나타남
- [ ] 웹 UI에 실시간 자막이 표시됨

### ⚠️ 문제 증상별 대응

**증상 1: "WebSocket이 이미 연결 중입니다" 경고 나타남**
```
⚠️ WebSocket이 이미 연결 중입니다. 중복 연결 방지.
```
- 원인: 버튼을 빠르게 여러 번 클릭
- 대응: 브라우저 새로고침 후 한 번만 클릭

**증상 2: "기존 WebSocket 연결이 있습니다" 경고 나타남**
```
⚠️ 기존 WebSocket 연결이 있습니다. 종료 후 새로 연결합니다.
```
- 원인: 이전 회의를 종료하지 않고 다시 시작
- 대응: "회의 종료" 버튼으로 먼저 끝낸 후 시작

**증상 3: AudioWorklet 로드 실패**
```
❌ AudioWorklet 로드 실패: ...
```
- 원인: 파일 경로 오류 또는 파일 누락
- 확인: 개발자 도구 Network 탭에서 `/audio-processor.worklet.js` 요청 상태
- 대응: 파일이 존재하는지 확인, 서버 재시작

**증상 4: JSON 파싱 실패**
```
⚠️ JSON 파싱 실패: ...
```
- 원인: 서버에서 잘못된 형식의 데이터 전송 (정상, 무시 가능)
- 대응: 이 경고는 정상적 - 음성 데이터로 인한 것

## 성능 목표 검증

### WebSocket 연결 안정성
- **목표**: 연결이 30초 이상 유지
- **확인**: "WebSocket connection closed" 메시지가 의도하지 않게 나타나지 않음

### 오디오 전송 레이턴시
- **목표**: < 2초 (음성 입력 후 서버에서 처리 시작)
- **확인**: "🔊 오디오 청크 전송" 메시지가 연속으로 나타남

### 실시간 자막 표시
- **목표**: 말한 지 2-3초 이내에 UI에 자막 나타남
- **확인**: "📨 WebSocket 메시지 수신: partial" 메시지가 나타나고 UI 업데이트

## 디버깅 팁

### 콘솔 필터링
```javascript
// 콘솔에서 특정 키워드로 필터링
// Example: "WebSocket" 검색
```

### 네트워크 탭 확인
1. F12 → Network 탭
2. Filter: "ws" (WebSocket만 표시)
3. 단일 연결만 나타나는지 확인

### 백엔드 로그 확인
```bash
docker-compose logs -f backend | grep -E "session|connected|disconnected"
```
- 단일 session_id만 나타나는지 확인
- 연결 시간과 종료 시간 비교

## 완료 확인

모든 검증 항목이 통과되면:
```bash
cd /home/proidea/Programming/stt_test
git status  # 모든 변경사항이 커밋되었는지 확인
```

테스트 결과를 정리하여 기록하면 완료입니다.
