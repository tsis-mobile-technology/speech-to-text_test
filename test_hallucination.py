#!/usr/bin/env python3
"""
할루시네이션 필터링 테스트 - API를 통한 검증
4가지 시나리오를 검증합니다
"""

import requests
import numpy as np
import soundfile as sf
import tempfile
import time
import json
from pathlib import Path


def generate_test_audio(scenario: str, duration_sec: float = 3.0, sample_rate: int = 16000) -> np.ndarray:
    """테스트 오디오 생성"""
    num_samples = int(sample_rate * duration_sec)

    if scenario == "silence":
        print(f"  🔇 생성: 침묵 ({duration_sec}초)")
        return np.zeros(num_samples, dtype=np.float32)

    elif scenario == "white_noise":
        print(f"  🌫️ 생성: 백색 잡음 ({duration_sec}초)")
        return np.random.uniform(-0.1, 0.1, num_samples).astype(np.float32)

    elif scenario == "music":
        print(f"  🎵 생성: 음악 ({duration_sec}초)")
        t = np.linspace(0, duration_sec, num_samples)
        freq1, freq2 = 10, 20
        audio = 0.2 * (np.sin(2 * np.pi * freq1 * t) + np.sin(2 * np.pi * freq2 * t))
        return audio.astype(np.float32)

    elif scenario == "normal_speech":
        print(f"  🎤 생성: 정상 음성 ({duration_sec}초)")
        t = np.linspace(0, duration_sec, num_samples)
        freq = np.linspace(200, 300, num_samples)
        audio = 0.3 * np.sin(2 * np.pi * freq * t / sample_rate)
        modulation = 0.1 * np.sin(2 * np.pi * 2 * t)
        return (audio + modulation).astype(np.float32)

    else:
        raise ValueError(f"Unknown scenario: {scenario}")


def test_scenario(scenario: str, base_url: str = "http://localhost:8000"):
    """한 가지 시나리오 테스트"""
    print(f"\n{'='*60}")
    print(f"테스트: {scenario.upper()}")
    print(f"{'='*60}")

    # 테스트 오디오 생성 및 저장
    audio_data = generate_test_audio(scenario, duration_sec=3.0)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
        sf.write(tmp_path, audio_data, 16000)
        print(f"  ✅ 파일 저장: {tmp_path}")

    try:
        # API로 업로드
        print(f"  📤 API로 업로드 중...")
        with open(tmp_path, 'rb') as f:
            files = {'audio_file': f}
            data = {'enable_diarization': False}
            response = requests.post(
                f"{base_url}/api/v1/transcribe",
                files=files,
                data=data,
                timeout=30
            )

        if response.status_code != 200:
            print(f"  ❌ API 오류: {response.status_code}")
            print(f"  응답: {response.text}")
            return -1

        result = response.json()
        session_id = result.get("session_id")
        print(f"  ✅ 세션 생성: {session_id}")

        # 처리 완료 대기 (최대 30초)
        print(f"  ⏳ 처리 중...", end="", flush=True)
        for attempt in range(30):
            time.sleep(1)
            session_response = requests.get(f"{base_url}/api/v1/sessions/{session_id}", timeout=10)
            if session_response.status_code == 200:
                session_data = session_response.json()
                if session_data.get("status") == "completed":
                    print(f" 완료!")

                    segments = session_data.get("segments", [])
                    print(f"\n  📊 결과: {len(segments)}개 세그먼트")

                    for i, seg in enumerate(segments, 1):
                        no_speech = seg.get("no_speech_prob", "N/A")
                        if isinstance(no_speech, float):
                            no_speech = f"{no_speech:.3f}"
                        print(
                            f"    [{i}] {seg['start']:.2f}s-{seg['end']:.2f}s | "
                            f"텍스트: '{seg['text'][:40]}' | "
                            f"신뢰도: {seg['confidence']:.2f} | "
                            f"no_speech_prob: {no_speech}"
                        )

                    return len(segments)
                elif session_data.get("status") == "failed":
                    print(f" 실패!")
                    print(f"  ❌ 오류: {session_data.get('error_message')}")
                    return -1
            print(".", end="", flush=True)

        print(f" 시간초과!")
        return -1

    finally:
        Path(tmp_path).unlink(missing_ok=True)


def main():
    """메인 테스트 루틴"""
    base_url = "http://localhost:8000"

    print("🚀 할루시네이션 필터링 테스트 시작")
    print(f"API: {base_url}")

    # 헬스 체크
    try:
        response = requests.get(f"{base_url}/api/v1/health", timeout=5)
        if response.status_code != 200:
            print("❌ API 접속 실패 - Docker 백엔드 실행 확인 필요")
            return False
        print("✅ API 정상 작동")
    except Exception as e:
        print(f"❌ API 연결 실패: {e}")
        return False

    results = {}

    # 4가지 시나리오 테스트
    scenarios = [
        ("silence", "침묵 - 필터링되어야 함 (예상: 0개)"),
        ("white_noise", "백색 잡음 - 필터링되어야 함 (예상: 0개)"),
        ("music", "음악 - 필터링되어야 함 (예상: 0개)"),
        ("normal_speech", "정상 음성 - 통과해야 함 (예상: ≥1개)"),
    ]

    for scenario, description in scenarios:
        print(f"\n✓ {description}")
        count = test_scenario(scenario, base_url)
        results[scenario] = count

    # 결과 요약
    print(f"\n\n{'='*60}")
    print("📈 테스트 결과 요약")
    print(f"{'='*60}")

    expected = {
        "silence": 0,        # 필터링
        "white_noise": 0,    # 필터링
        "music": 0,          # 필터링
        "normal_speech": 1,  # 통과 (1개 이상)
    }

    all_passed = True
    for scenario, expected_count in expected.items():
        actual_count = results.get(scenario, -1)
        if actual_count == -1:
            status = "❌ 오류"
            all_passed = False
        elif scenario == "normal_speech":
            status = "✅ 통과" if actual_count >= 1 else "❌ 실패"
            if actual_count < 1:
                all_passed = False
        else:
            status = "✅ 통과" if actual_count == 0 else "❌ 실패"
            if actual_count != 0:
                all_passed = False

        print(f"{scenario:15} | 예상: {expected_count:2}, 실제: {actual_count:2} | {status}")

    print(f"{'='*60}")
    if all_passed:
        print("🎉 모든 테스트 통과!")
    else:
        print("⚠️ 일부 테스트 실패")

    return all_passed


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
