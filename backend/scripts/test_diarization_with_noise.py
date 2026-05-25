#!/usr/bin/env python3
"""
화자 분리 정확도 검증 스크립트 (개선 버전)

실제 음성처럼 보이는 합성 데이터를 생성하여 테스트:
- 실제 한국어 음성 샘플 또는 TTS 사용
- 또는: 현실적인 음성 특성을 가진 합성 신호
  (노이즈, 스펙트럼 변화, 음성대역 신호)

대안으로 기존 테스트의 mock 모드를 활용하거나,
공개 음성 데이터셋을 다운로드하는 방법도 있습니다.
"""

import asyncio
import tempfile
import os
import logging
import numpy as np
import scipy.io.wavfile as wavfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.diarization import DiarizationEngine
from app.core.stt_engine import STTEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def generate_voice_like_signal(freq_base: float, modulation_freq: float = 2.0, duration: float = 5.0, sample_rate: int = 16000):
    """
    음성처럼 보이는 신호 생성:
    - 기본 주파수 (음성 피치)
    - 변조 (진폭과 주파수 변조로 음성의 음성대역 특성)
    - 노이즈 (음성의 무성음 성분)
    """
    samples = int(sample_rate * duration)
    t = np.arange(samples) / sample_rate

    # 기본 사인파 (음성 피치)
    carrier = np.sin(2 * np.pi * freq_base * t)

    # 진폭 변조 (음성의 강도 변화)
    amp_mod = 0.5 + 0.5 * np.sin(2 * np.pi * modulation_freq * t)

    # 주파수 변조 (음성의 톤 변화)
    freq_mod = np.sin(2 * np.pi * modulation_freq * t) * 20  # ±20Hz 변화
    fm_signal = np.sin(2 * np.pi * (freq_base + freq_mod) * t)

    # 노이즈 (음성의 마찰음 성분)
    noise = np.random.randn(samples) * 0.1

    # 조합
    signal = amp_mod * (0.6 * carrier + 0.3 * fm_signal) + noise

    # 정규화
    signal = np.clip(signal, -1.0, 1.0)
    signal = (signal * 32767).astype(np.int16)

    return signal


def generate_realistic_dialog(duration_sec: float = 30.0, sample_rate: int = 16000):
    """
    더 현실적인 2인 회의 시뮬레이션

    시나리오:
    - 00~05초: 화자 A (낮은 음역대, 100-150Hz)
    - 05~10초: 화자 B (높은 음역대, 180-220Hz)
    - 10~15초: 화자 A
    - 15~20초: 화자 B
    - 20~25초: 화자 A (약간 더 높은 톤)
    - 25~30초: 화자 B
    """
    samples = int(sample_rate * duration_sec)
    audio_data = np.zeros(samples, dtype=np.float32)
    ground_truth = []

    timeline = [
        (120, 0, 5, "SPEAKER_00"),      # 화자 A
        (200, 5, 10, "SPEAKER_01"),     # 화자 B
        (120, 10, 15, "SPEAKER_00"),    # 화자 A
        (200, 15, 20, "SPEAKER_01"),    # 화자 B
        (125, 20, 25, "SPEAKER_00"),    # 화자 A (톤 약간 변화)
        (200, 25, 30, "SPEAKER_01"),    # 화자 B
    ]

    for freq, start_sec, end_sec, speaker in timeline:
        start_idx = int(start_sec * sample_rate)
        end_idx = int(end_sec * sample_rate)

        # 음성처럼 보이는 신호 생성
        segment_duration = end_sec - start_sec
        signal = generate_voice_like_signal(freq, modulation_freq=2.0, duration=segment_duration, sample_rate=sample_rate)
        signal = signal.astype(np.float32) / 32767

        # 음소거 구간 삽입 (0.3초)
        fade_len = int(0.15 * sample_rate)
        signal[:fade_len] *= np.linspace(0, 1, fade_len)
        signal[-fade_len:] *= np.linspace(1, 0, fade_len)

        audio_data[start_idx:end_idx] += signal

        ground_truth.append({"start": start_sec, "end": end_sec, "speaker": speaker})

    # 클리핑 방지
    audio_data = np.clip(audio_data, -1.0, 1.0)
    audio_data = (audio_data * 32767).astype(np.int16)

    return audio_data, ground_truth


def compute_overlap(seg1: dict, seg2: dict) -> float:
    """두 시간 구간의 겹침 비율"""
    overlap_start = max(seg1["start"], seg2["start"])
    overlap_end = min(seg1["end"], seg2["end"])
    overlap = max(0.0, overlap_end - overlap_start)
    duration = seg1["end"] - seg1["start"]
    return overlap / duration if duration > 0 else 0.0


def evaluate_accuracy(predicted: list[dict], ground_truth: list[dict], iou_threshold: float = 0.5) -> dict:
    """화자 분리 정확도 평가"""
    tp = fp = fn = 0
    matched_predictions = set()

    for gt in ground_truth:
        best_iou = 0.0
        best_idx = -1

        for idx, pred in enumerate(predicted):
            if idx in matched_predictions:
                continue

            if gt["speaker"] != pred["speaker"]:
                continue

            intersection = compute_overlap(gt, pred)
            union = (gt["end"] - gt["start"]) + (pred["end"] - pred["start"]) - intersection
            iou = intersection / union if union > 0 else 0.0

            if iou > best_iou:
                best_iou = iou
                best_idx = idx

        if best_iou >= iou_threshold:
            tp += 1
            matched_predictions.add(best_idx)
        else:
            fn += 1

    fp = len(predicted) - tp

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1_score = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1_score": f1_score,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "total_ground_truth": len(ground_truth),
        "total_predicted": len(predicted)
    }


async def test_with_realistic_data():
    """현실적인 음성 데이터로 화자 분리 테스트"""
    logger.info("=" * 80)
    logger.info("화자 분리 정확도 검증 (현실적 음성 신호)")
    logger.info("=" * 80)

    try:
        # 1. 현실적인 음성 신호 생성
        logger.info("\n[Step 1] 현실적인 2인 회의 음성 신호 생성...")
        audio_data, ground_truth = generate_realistic_dialog(duration_sec=30.0)

        logger.info(f"✓ 음성 신호 생성 완료 (30초)")
        logger.info(f"✓ Ground Truth 구간:")
        for gt in ground_truth:
            logger.info(f"  - {gt['speaker']}: {gt['start']:.2f}~{gt['end']:.2f}초")

        # 2. 임시 파일 저장
        logger.info("\n[Step 2] WAV 파일 저장...")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        wavfile.write(temp_path, 16000, audio_data)
        logger.info(f"✓ 파일 저장: {temp_path} ({len(audio_data) // 16000}초)")

        try:
            # 3. Pyannote 화자 분리
            logger.info("\n[Step 3] Pyannote 화자 분리 실행...")
            diarizer = DiarizationEngine.get_instance()
            predicted = await diarizer.diarize(temp_path)

            logger.info(f"✓ 화자 분리 완료 (총 {len(predicted)} 세그먼트)")
            if predicted:
                logger.info(f"✓ 추론 결과:")
                for pred in predicted:
                    logger.info(f"  - {pred['speaker']}: {pred['start']:.2f}~{pred['end']:.2f}초")
            else:
                logger.warning("⚠️  세그먼트 감지 안됨 (음성 신호가 감지되지 않았을 수 있음)")

            # 4. STT 확인
            logger.info("\n[Step 4] STT 확인...")
            try:
                stt_engine = STTEngine.get_instance()
                stt_results = await stt_engine.transcribe(temp_path, language="ko")
                logger.info(f"✓ STT 결과: {len(stt_results)} 세그먼트")
            except Exception as e:
                logger.warning(f"STT 실행 실패: {e}")

            # 5. 정확도 평가
            logger.info("\n[Step 5] 정확도 평가...")
            if predicted:
                metrics = evaluate_accuracy(predicted, ground_truth, iou_threshold=0.5)

                logger.info(f"✓ 정확도 평가:")
                logger.info(f"  - Precision: {metrics['precision']:.2%}")
                logger.info(f"  - Recall: {metrics['recall']:.2%}")
                logger.info(f"  - F1-Score: {metrics['f1_score']:.2%}")
                logger.info(f"  - TP: {metrics['tp']}, FP: {metrics['fp']}, FN: {metrics['fn']}")

                if metrics['f1_score'] >= 0.85:
                    logger.info(f"✅ 목표 달성! F1-Score {metrics['f1_score']:.2%} >= 85%")
                    return True
                else:
                    logger.warning(f"⚠️  목표 미달: F1-Score {metrics['f1_score']:.2%} < 85%")
                    logger.info("💡 다음 개선 방향:")
                    logger.info("   1. 실제 한국어 음성 데이터 사용")
                    logger.info("   2. Pyannote 모델의 음성대역 감도 튜닝")
                    logger.info("   3. 전처리 (노이즈 감소, 정규화) 개선")
                    return False
            else:
                logger.warning("❌ 화자 분리 실패 - 음성 신호가 감지되지 않음")
                logger.info("💡 개선 방향:")
                logger.info("   1. 합성 음성 신호 대신 실제 음성 데이터 사용")
                logger.info("   2. 음성 특성 더 강화 (멜스펙트로그램 기반)")
                logger.info("   3. 한국어 TTS 데이터셋 활용")
                return False

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
                logger.info(f"\n임시 파일 삭제: {temp_path}")

    except Exception as e:
        logger.error(f"❌ 테스트 실패: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = asyncio.run(test_with_realistic_data())
    sys.exit(0 if success else 1)
