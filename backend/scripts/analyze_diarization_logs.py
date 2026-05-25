#!/usr/bin/env python3
"""
WebSocket 스트리밍 로그 분석 및 화자 분리 진단 도구

사용법:
  1. WebSocket 스트리밍을 종료한 후
  2. 백엔드 로그를 파일로 저장
  3. 이 스크립트로 분석

예시:
  docker compose logs backend > logs.txt
  python scripts/analyze_diarization_logs.py logs.txt
"""

import sys
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime


def parse_log_file(log_file):
    """로그 파일을 파싱하여 주요 이벤트 추출"""

    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    events = []

    for i, line in enumerate(lines):
        # WebSocket 연결 이벤트
        if "WebSocket accepted" in line:
            events.append({
                'type': 'ws_connect',
                'time': extract_time(line),
                'line': i + 1,
                'text': line.strip()
            })

        # 세션 생성
        if "Session created:" in line:
            session_id = extract_session_id(line)
            events.append({
                'type': 'session_create',
                'session_id': session_id,
                'time': extract_time(line),
                'line': i + 1,
                'text': line.strip()
            })

        # STT 처리
        if "Processing audio with duration" in line:
            match = re.search(r'(\d{2}):(\d{2})\.(\d{3})', line)
            duration = f"{match.group(1)}:{match.group(2)}.{match.group(3)}" if match else "unknown"
            events.append({
                'type': 'stt_start',
                'duration': duration,
                'time': extract_time(line),
                'line': i + 1,
                'text': line.strip()
            })

        # 세그먼트 전송
        if "📤 Sending" in line and "segments to client" in line:
            match = re.search(r'Sending (\d+) segments', line)
            count = int(match.group(1)) if match else 0
            events.append({
                'type': 'segments_sent',
                'count': count,
                'time': extract_time(line),
                'line': i + 1,
                'text': line.strip()
            })

        # Whisper 결과
        if "✅ Sent final:" in line:
            text = extract_text_from_final(line)
            events.append({
                'type': 'segment_final',
                'text': text,
                'time': extract_time(line),
                'line': i + 1
            })

        # 화자 분리 시작
        if "Final post-processing (Diarization)" in line:
            events.append({
                'type': 'diarization_start',
                'time': extract_time(line),
                'line': i + 1,
                'text': line.strip()
            })

        # Pyannote 화자 분리
        if "Diarization complete. Found" in line:
            match = re.search(r'Found (\d+) speech turns', line)
            count = int(match.group(1)) if match else 0
            events.append({
                'type': 'diarization_result',
                'count': count,
                'time': extract_time(line),
                'line': i + 1,
                'text': line.strip()
            })

        # 화자 정보 업데이트
        if "speaker_updated" in line:
            events.append({
                'type': 'speaker_updated',
                'time': extract_time(line),
                'line': i + 1,
                'text': line.strip()
            })

        # 최종 세션 완료
        if "Session" in line and "completed:" in line and "segments" in line:
            match = re.search(r'(\d+) segments, (\d+) speakers', line)
            segments = int(match.group(1)) if match else 0
            speakers = int(match.group(2)) if match else 0
            events.append({
                'type': 'session_complete',
                'segments': segments,
                'speakers': speakers,
                'time': extract_time(line),
                'line': i + 1,
                'text': line.strip()
            })

        # 에러
        if "❌" in line or "Error" in line:
            events.append({
                'type': 'error',
                'time': extract_time(line),
                'line': i + 1,
                'text': line.strip()
            })

    return events


def extract_time(line):
    """로그 라인에서 시간 추출"""
    match = re.search(r'(\d{2}):(\d{2}):(\d{2})', line)
    return f"{match.group(1)}:{match.group(2)}:{match.group(3)}" if match else "unknown"


def extract_session_id(line):
    """로그에서 세션 ID 추출"""
    match = re.search(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', line)
    return match.group(0) if match else "unknown"


def extract_text_from_final(line):
    """최종 세그먼트의 텍스트 추출"""
    match = re.search(r'✅ Sent final: (.+)$', line)
    return match.group(1) if match else "unknown"


def print_analysis(events):
    """분석 결과 출력"""

    print("\n" + "=" * 80)
    print("WebSocket STT 스트리밍 로그 분석")
    print("=" * 80)

    if not events:
        print("❌ 이벤트를 찾을 수 없습니다.")
        return

    # 타임라인
    print("\n📊 이벤트 타임라인:")
    print("-" * 80)

    for event in events:
        time_str = event.get('time', 'unknown')

        if event['type'] == 'ws_connect':
            print(f"  {time_str} | 🔗 WebSocket 연결")

        elif event['type'] == 'session_create':
            print(f"  {time_str} | 📋 세션 생성: {event.get('session_id', 'unknown')[:8]}...")

        elif event['type'] == 'stt_start':
            print(f"  {time_str} | ▶️ STT 처리 시작 ({event.get('duration')})")

        elif event['type'] == 'segments_sent':
            count = event.get('count', 0)
            print(f"  {time_str} | 📤 {count}개 세그먼트 전송")

        elif event['type'] == 'segment_final':
            text = event.get('text', '')[:40]
            print(f"  {time_str} | ✅ 세그먼트: '{text}...'")

        elif event['type'] == 'diarization_start':
            print(f"  {time_str} | 🔄 화자 분리 시작 (최종 처리)")

        elif event['type'] == 'diarization_result':
            count = event.get('count', 0)
            print(f"  {time_str} | 🎙️  {count}개 음성 구간 감지")

        elif event['type'] == 'speaker_updated':
            print(f"  {time_str} | 🔊 화자 정보 업데이트 완료")

        elif event['type'] == 'session_complete':
            segments = event.get('segments', 0)
            speakers = event.get('speakers', 0)
            print(f"  {time_str} | ✅ 세션 완료: {segments}개 세그먼트, {speakers}명 화자")

        elif event['type'] == 'error':
            text = event.get('text', '')[:50]
            print(f"  {time_str} | ❌ 에러: {text}...")

    # 통계
    print("\n📈 통계:")
    print("-" * 80)

    type_counts = defaultdict(int)
    for event in events:
        type_counts[event['type']] += 1

    stt_events = [e for e in events if e['type'] == 'stt_start']
    segment_events = [e for e in events if e['type'] == 'segment_final']
    diarization_events = [e for e in events if e['type'] == 'diarization_result']
    error_events = [e for e in events if e['type'] == 'error']
    complete_events = [e for e in events if e['type'] == 'session_complete']

    print(f"✅ 성공한 STT 처리: {len(stt_events)}회")
    print(f"📝 전송된 세그먼트: {len(segment_events)}개")
    print(f"🎙️  화자 분리 실행: {len(diarization_events)}회")

    if diarization_events:
        total_speech_turns = sum(e.get('count', 0) for e in diarization_events)
        print(f"   - 감지된 음성 구간: {total_speech_turns}개")

    if complete_events:
        final = complete_events[-1]
        print(f"📊 최종 결과:")
        print(f"   - 세그먼트: {final.get('segments', 0)}개")
        print(f"   - 화자: {final.get('speakers', 0)}명")

    if error_events:
        print(f"❌ 에러 발생: {len(error_events)}회")
        for error in error_events[:3]:
            print(f"   - {error.get('text', '')[:60]}...")

    # 결론
    print("\n" + "=" * 80)
    print("📋 분석 결론:")
    print("=" * 80)

    if diarization_events and complete_events:
        final = complete_events[-1]
        speakers = final.get('speakers', 0)

        if speakers >= 2:
            print(f"✅ 화자 분리 성공! {speakers}명의 화자 감지됨")
        elif speakers == 1:
            print(f"⚠️  화자 분리 실행되었으나 {speakers}명만 감지됨 (다중 화자 없음)")
        else:
            print(f"❌ 화자 분리 실패 (화자 0명 감지)")
    elif diarization_events:
        print("⚠️  화자 분리는 실행되었으나 최종 결과가 없음")
    else:
        print("❌ 화자 분리가 실행되지 않음")

    print("\n💡 권장사항:")
    if not diarization_events:
        print("  - 스트리밍 중에는 화자 분리가 실행되지 않습니다")
        print("  - 스트리밍을 종료(연결 끊김)해야 화자 분리가 자동 실행됩니다")
        print("  - 또는 /api/v1/transcribe를 사용하여 파일 업로드 후 화자 분리 실행")
    elif complete_events:
        final = complete_events[-1]
        speakers = final.get('speakers', 0)
        if speakers < 2:
            print("  - 실제 다중 화자 음성 데이터로 테스트하세요")
            print("  - AIHUB, Common Voice 데이터셋 활용 권장")
            print("  - Pyannote 파라미터 튜닝 필요할 수 있음")
        else:
            print(f"  - 화자 분리 정상 작동 ({speakers}명 감지)")
            print("  - 정확도 측정을 위해 ground truth와 비교하세요")

    print()


def main():
    if len(sys.argv) != 2:
        print("사용법: python analyze_diarization_logs.py <log_file>")
        print("예시: docker compose logs backend > logs.txt")
        print("      python analyze_diarization_logs.py logs.txt")
        sys.exit(1)

    log_file = sys.argv[1]

    if not Path(log_file).exists():
        print(f"❌ 파일을 찾을 수 없습니다: {log_file}")
        sys.exit(1)

    print(f"📂 분석 대상: {log_file}")

    events = parse_log_file(log_file)
    print_analysis(events)


if __name__ == "__main__":
    main()
