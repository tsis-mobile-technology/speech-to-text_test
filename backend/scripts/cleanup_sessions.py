#!/usr/bin/env python3
"""
분절(청크 단위) 세션 일괄 정리 스크립트.

이전 버그로 한 회의가 여러 짧은 세션으로 쪼개져 쌓인 경우, 짧거나/세그먼트가 거의 없거나/
실패한 세션을 골라 삭제한다.

특징
- 기본은 **dry-run**(미리보기만). 실제 삭제는 `--apply` 필요.
- 삭제는 백엔드 **REST DELETE API**로 수행 → 인메모리 캐시 + DB 동시 정리(정합성 유지).
- 세션 오디오 파일(`{audio_dir}/{session_id}.f32`)도 함께 제거.
- 진행중(processing) 세션은 기본 제외(활성 회의 보호). `--include-processing`로 포함.

사용 예
  # 미리보기 (호스트에서)
  python3 backend/scripts/cleanup_sessions.py
  # 실제 삭제
  python3 backend/scripts/cleanup_sessions.py --apply --yes
  # 컨테이너에서
  docker exec stt_backend python /app/scripts/cleanup_sessions.py --apply --yes \
      --base-url http://localhost:8000 --audio-dir /app/data/audio
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path


def fetch_sessions(base_url: str) -> list[dict]:
    url = base_url.rstrip("/") + "/api/v1/sessions"
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.load(r)


def delete_session(base_url: str, sid: str) -> bool:
    url = base_url.rstrip("/") + f"/api/v1/sessions/{sid}"
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        print(f"  ⚠️ DELETE 실패({sid}): HTTP {e.code}")
        return False


def classify(s: dict, min_segments: int, min_duration: float,
             include_processing: bool, include_failed: bool):
    """삭제 후보면 사유 리스트 반환, 아니면 None.
    핵심 원칙: 내용이 있는 세션은 보호. '세그먼트도 적고 + 길이도 짧은'(AND) 세션만 분절/빈 세션으로 정리.
    """
    status = s.get("status")
    if status == "processing" and not include_processing:
        return None  # 활성 회의 보호
    seg_count = len(s.get("segments") or [])
    dur = float(s.get("duration_sec") or 0)

    # 주 신호: 세그먼트도 적고 길이도 짧음 → 분절/빈 세션
    if seg_count < min_segments and dur < min_duration:
        rs = [f"segments<{min_segments}({seg_count})", f"duration<{min_duration}s({dur:.1f})"]
        if status == "failed":
            rs.append("failed")
        return rs

    # 보조(옵션): 실패 + 사실상 빈 세션만. 내용 많은 실패 회의는 보호.
    if include_failed and status == "failed" and seg_count < min_segments:
        return [f"failed+segments<{min_segments}({seg_count})"]

    return None


def main():
    default_audio = (Path(__file__).resolve().parent.parent / "data" / "audio")
    ap = argparse.ArgumentParser(description="분절 세션 일괄 정리")
    ap.add_argument("--base-url", default="http://localhost:8000", help="백엔드 주소")
    ap.add_argument("--audio-dir", default=str(default_audio), help="세션 오디오(.f32) 디렉터리")
    ap.add_argument("--min-segments", type=int, default=2, help="이 미만 세그먼트 세션은 정리 대상")
    ap.add_argument("--min-duration", type=float, default=10.0, help="이 미만(초) 세션은 정리 대상")
    ap.add_argument("--include-processing", action="store_true", help="processing 세션도 대상에 포함(주의)")
    ap.add_argument("--include-failed", action="store_true",
                    help="실패+거의 빈(segments<min) 세션도 추가 정리 (내용 많은 실패 회의는 보호)")
    ap.add_argument("--apply", action="store_true", help="실제 삭제 수행(미지정 시 dry-run)")
    ap.add_argument("--yes", action="store_true", help="삭제 확인 프롬프트 생략")
    args = ap.parse_args()

    try:
        sessions = fetch_sessions(args.base_url)
    except Exception as e:
        print(f"❌ 세션 목록 조회 실패({args.base_url}): {e}")
        sys.exit(1)

    candidates = []
    for s in sessions:
        reasons = classify(s, args.min_segments, args.min_duration,
                           args.include_processing, args.include_failed)
        if reasons:
            candidates.append((s, reasons))

    print(f"전체 세션: {len(sessions)}개 | 정리 대상: {len(candidates)}개 "
          f"(기준: segments<{args.min_segments} AND duration<{args.min_duration}s"
          f"{' | +실패빈세션' if args.include_failed else ''}"
          f"{' | processing 포함' if args.include_processing else ' | processing 제외'})\n")

    if not candidates:
        print("✅ 정리할 분절 세션이 없습니다.")
        return

    print(f"{'SESSION_ID':38} {'STATUS':10} {'SEG':>4} {'DUR(s)':>8}  사유")
    print("-" * 90)
    for s, reasons in candidates:
        print(f"{s['session_id']:38} {str(s.get('status')):10} "
              f"{len(s.get('segments') or []):>4} {float(s.get('duration_sec') or 0):>8.1f}  {', '.join(reasons)}")
    print()

    if not args.apply:
        print("ℹ️ DRY-RUN (미리보기). 실제 삭제하려면 --apply 를 추가하세요.")
        return

    if not args.yes:
        ans = input(f"위 {len(candidates)}개 세션을 영구 삭제합니다. 진행할까요? [y/N] ").strip().lower()
        if ans != "y":
            print("취소했습니다.")
            return

    deleted, audio_removed = 0, 0
    for s, _ in candidates:
        sid = s["session_id"]
        if delete_session(args.base_url, sid):
            deleted += 1
            # 오디오 파일 제거(best-effort)
            f = os.path.join(args.audio_dir, f"{sid}.f32")
            try:
                if os.path.exists(f):
                    os.remove(f)
                    audio_removed += 1
            except OSError as e:
                print(f"  ⚠️ 오디오 삭제 실패({sid}): {e}")

    print(f"\n✅ 완료: 세션 {deleted}/{len(candidates)}개 삭제, 오디오 파일 {audio_removed}개 제거")


if __name__ == "__main__":
    main()
