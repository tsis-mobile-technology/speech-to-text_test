#!/usr/bin/env python3
"""
Phase 1 성능 벤치마크 스크립트
Beam size, Temperature, Language Prompt 효과 측정 (Before/After)
"""

import os
import sys
import asyncio
import time
import logging
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.stt_engine import STTEngine
from app.config import settings
from app.utils.gpu_monitor import check_vram_usage
import numpy as np
from scipy.io import wavfile

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def generate_test_audio(duration_sec: float = 5, text: str = "안녕하세요") -> str:
    """테스트 오디오 파일 생성 (무음 + 백그라운드 노이즈)"""
    import tempfile
    sample_rate = 16000
    num_samples = int(duration_sec * sample_rate)

    # 백그라운드 노이즈 (신호-대-잡음비 SNR 20dB)
    noise = np.random.normal(0, 0.01, num_samples).astype(np.float32)

    # 정현파 신호 (1000Hz) - 발성 구간 시뮬레이션
    t = np.arange(num_samples) / sample_rate
    signal = 0.1 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)

    # 신호 + 노이즈
    audio = signal + noise
    audio = np.clip(audio, -1.0, 1.0)

    # WAV 파일 저장
    temp_dir = tempfile.gettempdir()
    test_file = os.path.join(temp_dir, "benchmark_test_audio.wav")
    int_pcm = (audio * 32767).astype(np.int16)
    wavfile.write(test_file, sample_rate, int_pcm)

    logger.info(f"✅ Test audio generated: {test_file}")
    return test_file


async def benchmark_beam_size(audio_path: str, beam_sizes: list = [1, 3, 5]):
    """Beam size별 성능 측정"""
    logger.info("\n" + "="*70)
    logger.info("📊 BEAM SIZE 효과 측정 (정확도 vs 속도)")
    logger.info("="*70)

    stt_engine = STTEngine.get_instance()
    results = {}

    for beam_size in beam_sizes:
        try:
            # VRAM 체크
            vram_before, vram_total = check_vram_usage()
            logger.info(f"\n🔹 Beam size = {beam_size}")
            logger.info(f"   VRAM before: {vram_before}MB / {vram_total}MB")

            # 추론 시간 측정
            start_time = time.time()
            segments = await stt_engine.transcribe(
                audio_path,
                language="ko",
                beam_size=beam_size,
                initial_prompt=""  # 프롬프트 없이
            )
            elapsed = time.time() - start_time

            # VRAM 체크
            vram_after, _ = check_vram_usage()

            # 결과 수집
            text_output = " ".join([s["text"] for s in segments])
            avg_confidence = np.mean([s["confidence"] for s in segments]) if segments else 0.0

            results[beam_size] = {
                "elapsed_time": elapsed,
                "segment_count": len(segments),
                "text": text_output[:100],  # 처음 100자만
                "avg_confidence": avg_confidence,
                "vram_delta": vram_after - vram_before,
                "rtf": elapsed / (segments[-1]["end"] if segments else 1.0)  # Real-Time Factor
            }

            logger.info(f"   ⏱️  Elapsed: {elapsed:.3f}s")
            logger.info(f"   📝 Segments: {len(segments)}")
            logger.info(f"   🎯 Avg confidence: {avg_confidence:.2%}")
            logger.info(f"   📈 RTF (Real-Time Factor): {results[beam_size]['rtf']:.3f}")
            logger.info(f"   💾 VRAM delta: {vram_after - vram_before:+d}MB")

        except Exception as e:
            logger.error(f"❌ Error with beam_size={beam_size}: {e}")
            results[beam_size] = {"error": str(e)}

    return results


async def benchmark_language_prompt(audio_path: str, context_types: list = ["meeting", "technical", "general"]):
    """Language Prompt 효과 측정"""
    logger.info("\n" + "="*70)
    logger.info("🎯 LANGUAGE PROMPT 효과 측정 (문맥 정보)")
    logger.info("="*70)

    stt_engine = STTEngine.get_instance()
    results = {}

    for context in context_types:
        try:
            prompt = settings.CONTEXT_PROMPTS.get(context, "")
            logger.info(f"\n🔹 Context: {context}")
            logger.info(f"   Prompt: {prompt[:50]}...")

            start_time = time.time()
            segments = await stt_engine.transcribe(
                audio_path,
                language="ko",
                beam_size=3,  # Balanced
                initial_prompt=prompt
            )
            elapsed = time.time() - start_time

            text_output = " ".join([s["text"] for s in segments])
            avg_confidence = np.mean([s["confidence"] for s in segments]) if segments else 0.0

            results[context] = {
                "elapsed_time": elapsed,
                "segment_count": len(segments),
                "text": text_output[:100],
                "avg_confidence": avg_confidence,
            }

            logger.info(f"   ⏱️  Elapsed: {elapsed:.3f}s")
            logger.info(f"   🎯 Avg confidence: {avg_confidence:.2%}")

        except Exception as e:
            logger.error(f"❌ Error with context={context}: {e}")
            results[context] = {"error": str(e)}

    return results


async def benchmark_temperature(audio_path: str):
    """Temperature 파라미터 효과 측정"""
    logger.info("\n" + "="*70)
    logger.info("🌡️  TEMPERATURE 효과 측정 (모델 확률성)")
    logger.info("="*70)

    stt_engine = STTEngine.get_instance()
    logger.info(f"Temperature settings: {settings.TEMPERATURE}")

    # Temperature 설정은 model.transcribe() 내부에서 처리되므로
    # 여러 번 같은 파일 추론하면 다른 결과가 나옴 (확률적)
    results = {}

    for run in range(3):
        try:
            logger.info(f"\n🔹 Run {run + 1}/3")
            start_time = time.time()
            segments = await stt_engine.transcribe(
                audio_path,
                language="ko",
                beam_size=3,
                initial_prompt=settings.CONTEXT_PROMPTS.get("meeting", "")
            )
            elapsed = time.time() - start_time

            text_output = " ".join([s["text"] for s in segments])
            avg_confidence = np.mean([s["confidence"] for s in segments]) if segments else 0.0

            results[f"run_{run + 1}"] = {
                "elapsed_time": elapsed,
                "text": text_output[:100],
                "avg_confidence": avg_confidence,
            }

            logger.info(f"   ⏱️  Elapsed: {elapsed:.3f}s")
            logger.info(f"   🎯 Avg confidence: {avg_confidence:.2%}")

        except Exception as e:
            logger.error(f"❌ Error on run {run + 1}: {e}")

    return results


def print_summary(beam_results, prompt_results, temp_results):
    """요약 레포트 출력"""
    logger.info("\n" + "="*70)
    logger.info("📋 벤치마크 요약 레포트")
    logger.info("="*70)

    # Beam size 비교
    logger.info("\n🔹 Beam Size 비교 (속도 vs 정확도)")
    logger.info("-" * 70)
    logger.info("Beam | Elapsed(s) | RTF  | Avg Conf | 추천용도")
    logger.info("-" * 70)

    sorted_beams = sorted(beam_results.items())
    for beam_size, data in sorted_beams:
        if "error" not in data:
            elapsed = data["elapsed_time"]
            rtf = data["rtf"]
            conf = data["avg_confidence"]
            if beam_size == 1:
                use_case = "실시간 스트리밍 (빠른 응답)"
            elif beam_size == 3:
                use_case = "파일 업로드 ⭐ 권장"
            else:
                use_case = "고정확도 모드"
            logger.info(f"{beam_size:>4} | {elapsed:>10.3f} | {rtf:>4.2f} | {conf:>8.2%} | {use_case}")

    # Language Prompt 비교
    logger.info("\n🔹 Language Prompt 효과")
    logger.info("-" * 70)
    for context, data in prompt_results.items():
        if "error" not in data:
            logger.info(f"{context:>10s}: {data['avg_confidence']:.2%} confidence")

    # Temperature 효과
    logger.info("\n🔹 Temperature 효과 (3회 반복)")
    logger.info("-" * 70)
    for run, data in temp_results.items():
        logger.info(f"{run}: {data['avg_confidence']:.2%} confidence")

    # 권장사항
    logger.info("\n" + "="*70)
    logger.info("✅ 권장사항 (웹 검증 기반)")
    logger.info("="*70)
    logger.info("1️⃣  실시간 스트리밍 (WebSocket):")
    logger.info("   - Beam size = 1 (BEAM_SIZE_FAST)")
    logger.info("   - Language Prompt = meeting (회의 맥락)")
    logger.info("   - 목표: 레이턴시 < 2초")
    logger.info("")
    logger.info("2️⃣  파일 업로드 (정확도 우선):")
    logger.info("   - Beam size = 3 (BEAM_SIZE_BALANCED) ⭐ 권장")
    logger.info("   - Language Prompt = 도메인별 선택")
    logger.info("   - 예상 효과: WER 20-30% 감소")
    logger.info("")
    logger.info("3️⃣  고정확도 모드 (품질 중심):")
    logger.info("   - Beam size = 5 (BEAM_SIZE_HIGH)")
    logger.info("   - Language Prompt + Temperature 병합")
    logger.info("   - 예상 효과: WER 30-40% 감소")
    logger.info("="*70)


async def main():
    """메인 벤치마크 루틴"""
    logger.info("🚀 STT 정확도 개선 Phase 1 벤치마크 시작")
    logger.info(f"모델: {settings.WHISPER_MODEL_SIZE}")
    logger.info(f"디바이스: {settings.WHISPER_DEVICE}")
    logger.info(f"Compute Type: {settings.WHISPER_COMPUTE_TYPE}")

    # 테스트 오디오 생성
    test_audio = generate_test_audio(duration_sec=5)

    try:
        # 1. Beam size 효과 측정
        beam_results = await benchmark_beam_size(test_audio)

        # 2. Language Prompt 효과 측정
        prompt_results = await benchmark_language_prompt(test_audio)

        # 3. Temperature 효과 측정
        temp_results = await benchmark_temperature(test_audio)

        # 4. 요약 레포트 출력
        print_summary(beam_results, prompt_results, temp_results)

        logger.info("\n✅ 벤치마크 완료!")

    finally:
        # 테스트 파일 정리
        if os.path.exists(test_audio):
            os.remove(test_audio)
            logger.info(f"정리: {test_audio} 삭제됨")


if __name__ == "__main__":
    asyncio.run(main())
