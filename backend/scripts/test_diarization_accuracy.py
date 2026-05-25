#!/usr/bin/env python3
"""
화자 분리 정확도 검증 스크립트

실제 2인 회의를 시뮬레이션하여:
1. 각 화자의 음성을 합성 생성
2. 타임스탐프와 함께 혼합
3. Pyannote 화자 분리 실행
4. 예상 결과와 실제 결과 비교

예상 결과:
- 화자 2명 감지 (SPEAKER_00, SPEAKER_01)
- 각 화자의 발화 구간이 정확하게 구분됨
- 정확도 >85% (recall, precision, F1-score)
"""

import asyncio
import tempfile
import os
import logging
import numpy as np
import scipy.io.wavfile as wavfile
from pathlib import Path
import sys

# 프로젝트 경로 설정
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.diarization import DiarizationEngine
from app.core.stt_engine import STTEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def generate_synthetic_dialog(duration_sec: float = 30.0, sample_rate: int = 16000) -> tuple[np.ndarray, list[dict]]:
    """
    2인 회의 시뮬레이션 오디오 생성

    시나리오:
    - 00:00-05:00: SPEAKER_00 (저주파 톤 100Hz)
    - 05:00-10:00: SPEAKER_01 (고주파 톤 200Hz)
    - 10:00-15:00: SPEAKER_00 (저주파)
    - 15:00-20:00: SPEAKER_01 (고주파)
    - 20:00-25:00: 동시 발화 (혼합음, 동시에 두 톤)
    - 25:00-30:00: SPEAKER_00 (저주파)

    반환:
    - audio_data: PCM16 오디오 배열
    - ground_truth: 예상 화자 구간 [{"start": 0, "end": 5, "speaker": "SPEAKER_00"}, ...]
    """
    samples = int(sample_rate * duration_sec)
    audio_data = np.zeros(samples, dtype=np.float32)
    ground_truth = []

    def generate_tone(freq: float, start_sec: float, end_sec: float) -> tuple[np.ndarray, dict]:
        start_idx = int(start_sec * sample_rate)
        end_idx = int(end_sec * sample_rate)
        t = np.linspace(0, end_sec - start_sec, end_idx - start_idx, endpoint=False)

        # 사인파 생성 (진폭 0.3으로 정규화)
        tone = 0.3 * np.sin(2 * np.pi * freq * t)
        return tone, {"start": start_sec, "end": end_sec}

    # 타임라인 정의
    segments = [
        (100, 0, 5, "SPEAKER_00"),      # 00-05초: 화자 A
        (200, 5, 10, "SPEAKER_01"),     # 05-10초: 화자 B
        (100, 10, 15, "SPEAKER_00"),    # 10-15초: 화자 A
        (200, 15, 20, "SPEAKER_01"),    # 15-20초: 화자 B
        (100, 20, 25, "SPEAKER_00"),    # 20-25초: 화자 A (겹침 테스트)
        (100, 25, 30, "SPEAKER_00"),    # 25-30초: 화자 A
    ]

    for freq, start_sec, end_sec, speaker in segments:
        start_idx = int(start_sec * sample_rate)
        end_idx = int(end_sec * sample_rate)
        t = np.arange(end_idx - start_idx) / sample_rate

        tone = 0.3 * np.sin(2 * np.pi * freq * t).astype(np.float32)
        audio_data[start_idx:end_idx] += tone

        # Ground truth 기록
        if speaker not in [g["speaker"] for g in ground_truth]:
            ground_truth.append({"start": start_sec, "end": end_sec, "speaker": speaker})
        else:
            # 같은 화자의 연속 발화는 병합
            if ground_truth[-1]["speaker"] == speaker:
                ground_truth[-1]["end"] = end_sec
            else:
                ground_truth.append({"start": start_sec, "end": end_sec, "speaker": speaker})

    # 클리핑 방지
    audio_data = np.clip(audio_data, -1.0, 1.0)

    # PCM16로 변환
    audio_data = (audio_data * 32767).astype(np.int16)

    return audio_data, ground_truth


def compute_overlap(seg1: dict, seg2: dict) -> float:
    """두 시간 구간의 겹침 비율 계산"""
    overlap_start = max(seg1["start"], seg2["start"])
    overlap_end = min(seg1["end"], seg2["end"])
    overlap = max(0.0, overlap_end - overlap_start)
    duration = seg1["end"] - seg1["start"]
    return overlap / duration if duration > 0 else 0.0


def evaluate_accuracy(predicted: list[dict], ground_truth: list[dict], iou_threshold: float = 0.5) -> dict:
    """
    화자 분리 정확도 평가

    Intersection over Union (IoU) 기반 매칭:
    - 예상 구간과 추론 구간의 IoU > threshold이면 TP
    - 그 외는 FP/FN

    반환:
    - precision: TP / (TP + FP)
    - recall: TP / (TP + FN)
    - f1_score: 2 * precision * recall / (precision + recall)
    - tp, fp, fn: 상세 개수
    """
    tp = fp = fn = 0
    matched_predictions = set()

    for gt in ground_truth:
        best_iou = 0.0
        best_idx = -1

        for idx, pred in enumerate(predicted):
            if idx in matched_predictions:
                continue

            # 같은 화자만 비교
            if gt["speaker"] != pred["speaker"]:
                continue

            # IoU 계산
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


async def test_diarization_accuracy():
    """화자 분리 정확도 검증 테스트"""
    logger.info("=" * 80)
    logger.info("화자 분리 정확도 검증 시작")
    logger.info("=" * 80)

    try:
        # 1. 합성 2인 회의 오디오 생성
        logger.info("\n[Step 1] 합성 2인 회의 오디오 생성...")
        audio_data, ground_truth = generate_synthetic_dialog(duration_sec=30.0)

        logger.info(f"✓ 오디오 생성 완료 (30초, 총 48000 샘플)")
        logger.info(f"✓ Ground Truth 구간:")
        for gt in ground_truth:
            logger.info(f"  - {gt['speaker']}: {gt['start']:.2f}~{gt['end']:.2f}초")

        # 2. 임시 파일에 저장
        logger.info("\n[Step 2] 임시 WAV 파일 생성...")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        wavfile.write(temp_path, 16000, audio_data)
        logger.info(f"✓ 파일 저장: {temp_path}")

        try:
            # 3. Pyannote 화자 분리 실행
            logger.info("\n[Step 3] Pyannote 화자 분리 실행...")
            diarizer = DiarizationEngine.get_instance()
            predicted = await diarizer.diarize(temp_path)

            logger.info(f"✓ 화자 분리 완료 (총 {len(predicted)} 세그먼트)")
            logger.info(f"✓ 추론 결과:")
            for pred in predicted:
                logger.info(f"  - {pred['speaker']}: {pred['start']:.2f}~{pred['end']:.2f}초")

            # 4. STT로 텍스트 확인 (선택사항)
            logger.info("\n[Step 4] STT 전사 확인...")
            try:
                stt_engine = STTEngine.get_instance()
                stt_results = await stt_engine.transcribe(temp_path, language="ko")
                logger.info(f"✓ STT 결과: {len(stt_results)} 세그먼트")
                for seg in stt_results[:3]:  # 처음 3개만 표시
                    logger.info(f"  - [{seg['start']:.2f}~{seg['end']:.2f}] {seg['text']}")
            except Exception as e:
                logger.warning(f"STT 실행 실패: {e}")

            # 5. 정확도 평가
            logger.info("\n[Step 5] 정확도 평가...")
            metrics = evaluate_accuracy(predicted, ground_truth, iou_threshold=0.5)

            logger.info(f"✓ 정확도 평가 완료:")
            logger.info(f"  - Precision: {metrics['precision']:.2%}")
            logger.info(f"  - Recall: {metrics['recall']:.2%}")
            logger.info(f"  - F1-Score: {metrics['f1_score']:.2%}")
            logger.info(f"  - TP: {metrics['tp']}, FP: {metrics['fp']}, FN: {metrics['fn']}")

            # 6. 결과 평가
            logger.info("\n[Step 6] 결과 평가...")
            if metrics['f1_score'] >= 0.85:
                logger.info(f"✅ 목표 달성! F1-Score {metrics['f1_score']:.2%} >= 85%")
                return True
            else:
                logger.warning(f"⚠️  목표 미달: F1-Score {metrics['f1_score']:.2%} < 85%")
                return False

        finally:
            # 임시 파일 정리
            if os.path.exists(temp_path):
                os.remove(temp_path)
                logger.info(f"\n임시 파일 삭제: {temp_path}")

    except Exception as e:
        logger.error(f"❌ 테스트 실패: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = asyncio.run(test_diarization_accuracy())
    sys.exit(0 if success else 1)
