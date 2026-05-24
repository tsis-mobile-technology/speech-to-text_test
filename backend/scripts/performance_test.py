#!/usr/bin/env python3
"""
성능 테스트 스크립트
- STT 엔진 처리 속도 (RTF - Real-Time Factor)
- GPU 메모리 사용량
- 화자 분리 정확도
- 파이프라인 지연 시간
"""

import asyncio
import time
import numpy as np
import scipy.io.wavfile as wavfile
import tempfile
import os
from pathlib import Path
from tabulate import tabulate

# 상대 임포트 수정
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.stt_engine import STTEngine, WHISPER_AVAILABLE
from app.core.diarization import DiarizationEngine, PYANNOTE_AVAILABLE
from app.core.audio_processor import AudioProcessor
from app.utils.gpu_monitor import GPUMonitor


class PerformanceTester:
    def __init__(self):
        self.results = []
        self.gpu_monitor = GPUMonitor()

    def generate_test_audio(self, duration: float, frequency: float = 440.0) -> str:
        """테스트용 사인파 오디오 파일 생성"""
        sample_rate = 16000
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        audio_data = np.sin(2 * np.pi * frequency * t)
        audio_data = (audio_data * 32767).astype(np.int16)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        wavfile.write(temp_path, sample_rate, audio_data)
        return temp_path

    async def test_stt_engine(self):
        """STT 엔진 성능 테스트"""
        print("\n📊 STT 엔진 성능 테스트")
        print("=" * 50)

        if not WHISPER_AVAILABLE:
            print("⚠️  faster-whisper이 설치되지 않았습니다.")
            return

        engine = STTEngine.get_instance()
        engine.load_model()

        test_cases = [
            ("1초", 1.0),
            ("5초", 5.0),
            ("10초", 10.0),
            ("30초", 30.0),
        ]

        for name, duration in test_cases:
            audio_file = self.generate_test_audio(duration)

            try:
                # VRAM 기초선
                vram_before = self.gpu_monitor.get_vram_usage()[0]

                # 처리 시간 측정
                start = time.time()
                result = await engine.transcribe(audio_file)
                elapsed = time.time() - start

                # VRAM 피크
                vram_after = self.gpu_monitor.get_vram_usage()[0]

                # RTF 계산: (처리 시간 / 오디오 시간)
                rtf = elapsed / duration if duration > 0 else 0

                self.results.append({
                    "테스트": f"STT {name}",
                    "오디오 시간": f"{duration:.1f}s",
                    "처리 시간": f"{elapsed:.2f}s",
                    "RTF": f"{rtf:.3f}",
                    "VRAM Δ": f"{vram_after - vram_before:.0f}MB",
                    "결과 세그먼트": len(result),
                })

            finally:
                os.remove(audio_file)

    async def test_diarization(self):
        """화자 분리 성능 테스트"""
        print("\n📊 화자 분리 엔진 성능 테스트")
        print("=" * 50)

        if not PYANNOTE_AVAILABLE:
            print("⚠️  pyannote.audio가 설치되지 않았습니다.")
            return

        engine = DiarizationEngine.get_instance()
        engine.load_model()

        test_cases = [
            ("10초", 10.0),
            ("30초", 30.0),
        ]

        for name, duration in test_cases:
            audio_file = self.generate_test_audio(duration)

            try:
                vram_before = self.gpu_monitor.get_vram_usage()[0]

                start = time.time()
                result = await engine.diarize(audio_file)
                elapsed = time.time() - start

                vram_after = self.gpu_monitor.get_vram_usage()[0]

                self.results.append({
                    "테스트": f"화자분리 {name}",
                    "오디오 시간": f"{duration:.1f}s",
                    "처리 시간": f"{elapsed:.2f}s",
                    "RTF": f"{elapsed / duration:.3f}",
                    "VRAM Δ": f"{vram_after - vram_before:.0f}MB",
                    "결과 세그먼트": len(result),
                })

            finally:
                os.remove(audio_file)

    def test_audio_processor(self):
        """오디오 처리 성능 테스트"""
        print("\n📊 오디오 처리 성능 테스트")
        print("=" * 50)

        processor = AudioProcessor()

        # PCM 청크 생성
        sample_rate = 16000
        chunk_size = 500  # 500ms
        num_chunks = 20

        chunks = []
        for _ in range(num_chunks):
            audio_data = np.random.randn(chunk_size * sample_rate // 1000).astype(np.float32)
            chunks.append(audio_data)

        # 처리 시간 측정
        start = time.time()
        for chunk in chunks:
            processor.add_audio_chunk(chunk, sample_rate)
        elapsed = time.time() - start

        total_duration = (chunk_size * num_chunks) / 1000.0

        self.results.append({
            "테스트": "오디오 버퍼",
            "오디오 시간": f"{total_duration:.1f}s",
            "처리 시간": f"{elapsed:.3f}s",
            "RTF": f"{elapsed / total_duration:.4f}",
            "VRAM Δ": "0MB",
            "결과 세그먼트": "N/A",
        })

    def test_gpu_memory(self):
        """GPU 메모리 사용량 모니터링"""
        print("\n📊 GPU 메모리 모니터링")
        print("=" * 50)

        try:
            used, total = self.gpu_monitor.get_vram_usage()
            percent = (used / total) * 100

            print(f"사용 중: {used:.0f}MB / {total:.0f}MB ({percent:.1f}%)")

            if percent > 70:
                print("⚠️  GPU 메모리 사용량이 높습니다.")
            elif percent < 30:
                print("✅ GPU 메모리 여유가 있습니다.")

        except Exception as e:
            print(f"❌ GPU 모니터링 실패: {e}")

    async def run_all_tests(self):
        """모든 테스트 실행"""
        print("\n" + "=" * 70)
        print("🚀 STT 시스템 성능 테스트 시작")
        print("=" * 70)

        # GPU 메모리 체크
        self.test_gpu_memory()

        # STT 테스트
        try:
            await self.test_stt_engine()
        except Exception as e:
            print(f"❌ STT 테스트 실패: {e}")

        # 화자 분리 테스트
        try:
            await self.test_diarization()
        except Exception as e:
            print(f"❌ 화자 분리 테스트 실패: {e}")

        # 오디오 처리 테스트
        try:
            self.test_audio_processor()
        except Exception as e:
            print(f"❌ 오디오 처리 테스트 실패: {e}")

        # 결과 출력
        print("\n" + "=" * 70)
        print("📈 성능 테스트 결과")
        print("=" * 70)

        if self.results:
            print(tabulate(self.results, headers="keys", tablefmt="grid"))

            # 성능 목표 검증
            print("\n✅ 성능 목표 검증")
            print("=" * 70)

            rtf_values = []
            for result in self.results:
                if "STT" in result["테스트"]:
                    rtf = float(result["RTF"])
                    rtf_values.append(rtf)

                    if rtf < 0.3:
                        status = "✅"
                    elif rtf < 0.5:
                        status = "⚠️"
                    else:
                        status = "❌"

                    print(f"{status} {result['테스트']}: RTF = {rtf:.3f} (목표: < 0.3)")

        else:
            print("⚠️  결과가 없습니다.")


async def main():
    tester = PerformanceTester()
    try:
        await tester.run_all_tests()
    finally:
        # 모델 정리
        stt = STTEngine.get_instance()
        stt.release()

        diar = DiarizationEngine.get_instance()
        diar.release()


if __name__ == "__main__":
    asyncio.run(main())
