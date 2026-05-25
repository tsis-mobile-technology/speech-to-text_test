#!/usr/bin/env python3
"""
할루시네이션 필터링 테스트 스크립트
4가지 시나리오를 검증합니다:
1. 음악 (노래) - 필터링되어야 함
2. 침묵 (무음) - 필터링되어야 함
3. 백색 잡음 - 필터링되어야 함
4. 정상 음성 - 통과해야 함
"""

import asyncio
import numpy as np
import os
import sys
import logging
from pathlib import Path
import soundfile as sf

# 프로젝트 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.core.stt_engine import STTEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def generate_test_audio(scenario: str, duration_sec: float = 3.0, sample_rate: int = 16000) -> np.ndarray:
    """테스트 오디오 생성"""
    num_samples = int(sample_rate * duration_sec)

    if scenario == "silence":
        # 침묵 (모두 0)
        logger.info(f"🔇 생성: 침묵 ({duration_sec}초)")
        return np.zeros(num_samples, dtype=np.float32)

    elif scenario == "white_noise":
        # 백색 잡음 (0.1 범위의 랜덤)
        logger.info(f"🌫️ 생성: 백색 잡음 ({duration_sec}초)")
        return np.random.uniform(-0.1, 0.1, num_samples).astype(np.float32)

    elif scenario == "music":
        # 음악 모사 (10Hz + 20Hz 사인파 조합)
        logger.info(f"🎵 생성: 음악 ({duration_sec}초)")
        t = np.linspace(0, duration_sec, num_samples)
        freq1, freq2 = 10, 20  # Low frequency music-like pattern
        audio = 0.2 * (np.sin(2 * np.pi * freq1 * t) + np.sin(2 * np.pi * freq2 * t))
        return audio.astype(np.float32)

    elif scenario == "normal_speech":
        # 정상 음성 모사 (200-300Hz 음성 대역)
        logger.info(f"🎤 생성: 정상 음성 ({duration_sec}초)")
        t = np.linspace(0, duration_sec, num_samples)
        # 음성 대역 주파수 (약 200-300Hz)
        freq = np.linspace(200, 300, num_samples)
        audio = 0.3 * np.sin(2 * np.pi * freq * t / sample_rate)
        # 약간의 주파수 변조 추가
        modulation = 0.1 * np.sin(2 * np.pi * 2 * t)  # 2Hz modulation
        return (audio + modulation).astype(np.float32)

    else:
        raise ValueError(f"Unknown scenario: {scenario}")


async def test_scenario(scenario: str, sample_rate: int = 16000):
    """한 가지 시나리오 테스트"""
    logger.info(f"\n{'='*60}")
    logger.info(f"테스트: {scenario.upper()}")
    logger.info(f"{'='*60}")

    # 테스트 오디오 생성 (3초)
    audio_data = generate_test_audio(scenario, duration_sec=3.0, sample_rate=sample_rate)

    # 임시 WAV 파일로 저장
    test_file = f"/tmp/test_{scenario}.wav"
    sf.write(test_file, audio_data, sample_rate)
    logger.info(f"✅ 파일 저장: {test_file}")

    try:
        # STT 엔진으로 처리
        stt_engine = STTEngine.get_instance()
        results = await stt_engine.transcribe(
            test_file,
            language=None,
            beam_size=1,  # 빠른 처리
            initial_prompt=None
        )

        logger.info(f"\n📊 결과: {len(results)}개 세그먼트")

        if results:
            for i, seg in enumerate(results, 1):
                logger.info(
                    f"  [{i}] {seg['start']:.2f}s-{seg['end']:.2f}s | "
                    f"텍스트: '{seg['text'][:50]}' | "
                    f"신뢰도: {seg['confidence']:.2f} | "
                    f"no_speech_prob: {seg.get('no_speech_prob', 'N/A')}"
                )
        else:
            logger.warning("❌ 결과 없음 (모두 필터링됨)")

        return len(results)

    except Exception as e:
        logger.error(f"❌ 오류: {e}", exc_info=True)
        return -1
    finally:
        # 임시 파일 삭제
        if os.path.exists(test_file):
            os.remove(test_file)


async def main():
    """메인 테스트 루틴"""
    logger.info("🚀 할루시네이션 필터링 테스트 시작")
    logger.info(f"설정값:")
    logger.info(f"  - CONFIDENCE_THRESHOLD: {settings.CONFIDENCE_THRESHOLD}")
    logger.info(f"  - NO_SPEECH_THRESHOLD: {settings.NO_SPEECH_THRESHOLD}")
    logger.info(f"  - MIN_SEGMENT_LENGTH: {settings.MIN_SEGMENT_LENGTH}초")
    logger.info(f"  - REPETITION_THRESHOLD: {settings.REPETITION_THRESHOLD}")
    logger.info(f"  - VAD_FILTER_ENABLED: {settings.VAD_FILTER_ENABLED}")

    results = {}

    # 4가지 시나리오 테스트
    scenarios = [
        ("silence", "침묵 - 필터링되어야 함"),
        ("white_noise", "백색 잡음 - 필터링되어야 함"),
        ("music", "음악 - 필터링되어야 함"),
        ("normal_speech", "정상 음성 - 통과해야 함"),
    ]

    for scenario, description in scenarios:
        logger.info(f"\n✓ {description}")
        count = await test_scenario(scenario)
        results[scenario] = count

    # 결과 요약
    logger.info(f"\n\n{'='*60}")
    logger.info("📈 테스트 결과 요약")
    logger.info(f"{'='*60}")

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
            # 정상 음성은 1개 이상 통과해야 함
            status = "✅ 통과" if actual_count >= 1 else "❌ 실패"
            if actual_count < 1:
                all_passed = False
        else:
            # 나머지는 모두 필터링되어야 함 (0개)
            status = "✅ 통과" if actual_count == 0 else "❌ 실패"
            if actual_count != 0:
                all_passed = False

        logger.info(f"{scenario:15} | 예상: {expected_count}, 실제: {actual_count} | {status}")

    logger.info(f"{'='*60}")
    if all_passed:
        logger.info("🎉 모든 테스트 통과!")
    else:
        logger.warning("⚠️ 일부 테스트 실패 - 설정값 조정 필요")

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
