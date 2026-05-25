#!/usr/bin/env python3
"""
세션 저장소 상태 진단 도구

현재 실행 중인 백엔드의 세션 상태를 HTTP로 확인합니다.
"""

import asyncio
import aiohttp
import json
import sys
from typing import Optional

async def test_session_endpoints():
    """모든 세션 관련 엔드포인트 테스트"""

    base_url = "http://localhost:8000/api/v1"

    print("\n" + "=" * 80)
    print("세션 저장소 상태 진단")
    print("=" * 80)

    async with aiohttp.ClientSession() as session:
        # 1. 헬스 체크
        print("\n[1] 헬스 체크")
        print("-" * 80)
        try:
            async with session.get(f"{base_url}/health") as resp:
                data = await resp.json()
                print(f"✅ 상태: {resp.status}")
                print(f"📊 응답: {json.dumps(data, indent=2, ensure_ascii=False)}")
        except Exception as e:
            print(f"❌ 에러: {e}")

        # 2. 모든 세션 조회
        print("\n[2] 모든 세션 조회 (GET /api/v1/sessions)")
        print("-" * 80)
        try:
            async with session.get(f"{base_url}/sessions") as resp:
                print(f"상태 코드: {resp.status}")

                if resp.status == 200:
                    data = await resp.json()
                    print(f"✅ 저장된 세션: {len(data)}개")

                    if data:
                        for i, sess in enumerate(data, 1):
                            print(f"\n   {i}. Session ID: {sess.get('session_id', 'unknown')[:8]}...")
                            print(f"      상태: {sess.get('status')}")
                            print(f"      세그먼트: {len(sess.get('segments', []))}개")
                            print(f"      화자: {sess.get('speaker_count')}명")

                            # 화자 정보 확인
                            speakers = set()
                            for seg in sess.get('segments', []):
                                if seg.get('speaker'):
                                    speakers.add(seg['speaker'])
                            print(f"      감지된 화자: {', '.join(sorted(speakers)) if speakers else 'None'}")
                    else:
                        print("   세션이 없습니다")

                elif resp.status == 404:
                    print(f"❌ 404 Not Found - 엔드포인트를 찾을 수 없습니다")
                    print("   디버그: 라우터가 제대로 등록되지 않았을 수 있습니다")
                else:
                    print(f"❌ 예상치 못한 상태 코드: {resp.status}")

        except Exception as e:
            print(f"❌ 에러: {e}")

        # 3. 특정 세션 조회 (최근 세션)
        print("\n[3] 최근 세션 상세 조회")
        print("-" * 80)
        try:
            async with session.get(f"{base_url}/sessions") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        latest_session = data[0]  # 첫 번째가 최신 (역순 정렬)
                        session_id = latest_session.get('session_id')

                        print(f"세션 ID: {session_id}")

                        async with session.get(f"{base_url}/sessions/{session_id}") as detail_resp:
                            print(f"상태 코드: {detail_resp.status}")

                            if detail_resp.status == 200:
                                detail = await detail_resp.json()
                                print(f"✅ 세션 상세:")
                                print(f"   상태: {detail.get('status')}")
                                print(f"   기간: {detail.get('duration_sec')}초")
                                print(f"   화자: {detail.get('speaker_count')}명")
                                print(f"   세그먼트: {len(detail.get('segments', []))}개")

                                # 화자 정보 상세
                                speakers = {}
                                for seg in detail.get('segments', []):
                                    speaker = seg.get('speaker', 'Unknown')
                                    if speaker not in speakers:
                                        speakers[speaker] = []
                                    speakers[speaker].append({
                                        'text': seg.get('text', '')[:50] + '...',
                                        'start': seg.get('start'),
                                        'end': seg.get('end'),
                                        'confidence': seg.get('confidence')
                                    })

                                print(f"\n   화자별 발화:")
                                for speaker, utterances in sorted(speakers.items()):
                                    print(f"   - {speaker}: {len(utterances)}개 발화")
                                    for j, utt in enumerate(utterances[:2], 1):  # 처음 2개만 표시
                                        print(f"     {j}. '{utt['text']}' ({utt['start']:.1f}~{utt['end']:.1f}s, conf: {utt['confidence']:.2f})")
                                    if len(utterances) > 2:
                                        print(f"     ... 외 {len(utterances)-2}개")
                            elif detail_resp.status == 404:
                                print(f"❌ 404 Not Found - 세션을 찾을 수 없습니다")
                            else:
                                print(f"❌ 에러: {detail_resp.status}")
                    else:
                        print("세션이 없으므로 상세 조회 불가")
        except Exception as e:
            print(f"❌ 에러: {e}")

    # 최종 진단
    print("\n" + "=" * 80)
    print("📋 진단 결과")
    print("=" * 80)

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{base_url}/sessions") as resp:
                if resp.status == 404:
                    print("""
❌ 문제: GET /api/v1/sessions 엔드포인트가 404

원인 가능성:
  1. 백엔드 컨테이너가 최신 코드를 사용하지 않음
  2. 라우터가 제대로 등록되지 않음
  3. 프론트엔드의 API 호출 경로가 잘못됨

해결책:
  1. 컨테이너 재시작: docker compose restart backend
  2. 또는 docker compose down && docker compose up -d
  3. 또는 main.py에서 라우터 등록 확인
""")
                elif resp.status == 200:
                    data = await resp.json()
                    if data:
                        print(f"""
✅ 정상 작동

저장된 세션: {len(data)}개
최근 세션:
  - Session ID: {data[0].get('session_id', 'unknown')[:16]}...
  - 상태: {data[0].get('status')}
  - 세그먼트: {len(data[0].get('segments', []))}개
  - 화자: {data[0].get('speaker_count')}명

✨ 화자 분리가 작동하고 있습니다!
""")
                    else:
                        print("""
⚠️  경고: 엔드포인트는 정상이지만 저장된 세션이 없습니다

가능한 원인:
  1. 세션이 TTL 만료로 삭제됨 (기본값: 1시간)
  2. 새로운 스트리밍을 아직 실행하지 않음

해결책:
  1. WebSocket 스트리밍 또는 파일 업로드 실행
  2. GET /api/v1/sessions로 다시 확인
""")
        except Exception as e:
            print(f"❌ 진단 실패: {e}")

    print()

if __name__ == "__main__":
    try:
        asyncio.run(test_session_endpoints())
    except KeyboardInterrupt:
        print("\n⏹️  중단됨")
        sys.exit(0)
