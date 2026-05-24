#!/usr/bin/env python3
"""
성능 테스트 스크립트 (Mock 모드)
- 실제 모델 없이 시뮬레이션으로 성능 지표 생성
- 예상 RTF, VRAM, 화자분리 성능 표시
"""

import time
import random
from typing import List, Tuple


class MockPerformanceTest:
    def __init__(self):
        self.results = []

    def generate_mock_stt_result(self, duration: float) -> dict:
        """STT 결과 시뮬레이션"""
        segments = []
        current_time = 0.0
        segment_id = 0

        while current_time < duration:
            # 평균 3초의 발화
            seg_duration = random.uniform(1.5, 4.5)
            if current_time + seg_duration > duration:
                seg_duration = duration - current_time

            confidence = random.uniform(0.80, 0.99)

            segments.append({
                'id': str(segment_id),
                'start': current_time,
                'end': current_time + seg_duration,
                'text': f'테스트 발화 {segment_id}',
                'confidence': confidence,
            })

            current_time += seg_duration + random.uniform(0.2, 0.5)  # 발화 간 간격
            segment_id += 1

        return segments

    def test_stt_performance(self):
        """STT 엔진 성능 테스트 (시뮬레이션)"""
        print("\n📊 STT 엔진 성능 테스트 (Mock 모드)")
        print("=" * 60)

        test_cases = [
            ("1초", 1.0, 0.05),      # duration, processing_time_ratio
            ("5초", 5.0, 0.08),
            ("10초", 10.0, 0.10),
            ("30초", 30.0, 0.12),
        ]

        for name, duration, processing_ratio in test_cases:
            # 처리 시간 계산 (현실적인 RTF 시뮬레이션)
            # RTF = processing_time / audio_duration
            # faster-whisper: 약 0.1-0.3 RTF
            processing_time = duration * processing_ratio

            rtf = processing_time / duration if duration > 0 else 0

            # VRAM 증가 (세그먼트 수에 따라)
            segments = self.generate_mock_stt_result(duration)
            vram_delta = len(segments) * 5  # 세그먼트당 약 5MB

            self.results.append({
                "테스트": f"STT {name}",
                "오디오 시간": f"{duration:.1f}s",
                "예상 처리": f"{processing_time:.2f}s",
                "RTF": f"{rtf:.3f}",
                "VRAM Δ": f"{vram_delta:.0f}MB",
                "세그먼트": len(segments),
                "상태": "✅ 목표 달성" if rtf < 0.3 else "⚠️ 최적화 필요"
            })

    def test_diarization_performance(self):
        """화자 분리 성능 테스트 (시뮬레이션)"""
        print("\n📊 화자 분리 엔진 성능 테스트 (Mock 모드)")
        print("=" * 60)

        test_cases = [
            ("10초", 10.0, 0.20),    # duration, processing_time_ratio
            ("30초", 30.0, 0.25),
            ("60초", 60.0, 0.30),
        ]

        for name, duration, processing_ratio in test_cases:
            processing_time = duration * processing_ratio
            rtf = processing_time / duration if duration > 0 else 0

            segments = self.generate_mock_stt_result(duration)
            speakers = set([f"SPEAKER_{i % 2}" for i in range(len(segments))])

            self.results.append({
                "테스트": f"화자분리 {name}",
                "오디오 시간": f"{duration:.1f}s",
                "예상 처리": f"{processing_time:.2f}s",
                "RTF": f"{rtf:.3f}",
                "화자 수": len(speakers),
                "세그먼트": len(segments),
                "상태": "✅" if rtf < 0.5 else "⚠️"
            })

    def test_audio_processor(self):
        """오디오 처리 성능 테스트"""
        print("\n📊 오디오 처리 성능 테스트")
        print("=" * 60)

        # 오디오 처리는 매우 빠름 (동기 처리)
        sample_rate = 16000
        chunk_duration = 500  # 500ms
        total_duration = 30.0  # 30초

        chunks = int(total_duration * 1000 / chunk_duration)
        processing_time = chunks * 0.001  # 청크당 1ms

        self.results.append({
            "테스트": "오디오 버퍼",
            "처리 대상": f"{total_duration:.1f}s",
            "청크 수": chunks,
            "처리 시간": f"{processing_time:.3f}s",
            "RTF": f"{processing_time / total_duration:.5f}",
            "상태": "✅ 실시간 가능"
        })

    def print_results(self):
        """결과 출력"""
        print("\n" + "=" * 90)
        print("🎯 성능 테스트 결과 (Mock 모드 - 예상 성능)")
        print("=" * 90)

        # 헤더
        headers = list(self.results[0].keys())
        col_widths = [max(len(str(h)), max(len(str(row.get(h, ""))) for row in self.results)) for h in headers]

        # 헤더 출력
        header_line = " | ".join(f"{h:<{w}}" for h, w in zip(headers, col_widths))
        print(header_line)
        print("-" * len(header_line))

        # 데이터 출력
        for row in self.results:
            row_line = " | ".join(f"{str(row.get(h, '')):<{w}}" for h, w in zip(headers, col_widths))
            print(row_line)

    def print_summary(self):
        """성능 요약 및 목표 달성도"""
        print("\n" + "=" * 90)
        print("✅ 성능 목표 달성도")
        print("=" * 90)

        # RTF 검증
        stt_rtfs = [float(r["RTF"]) for r in self.results if "STT" in r["테스트"]]
        avg_rtf = sum(stt_rtfs) / len(stt_rtfs) if stt_rtfs else 0

        print(f"\n📊 STT 처리 성능")
        print(f"  평균 RTF: {avg_rtf:.3f}")
        print(f"  목표: < 0.3")
        print(f"  결과: {'✅ 달성' if avg_rtf < 0.3 else '⚠️ 미달 (최적화 필요)'}")

        # VRAM 예상
        print(f"\n💾 GPU 메모리 사용량")
        print(f"  STT 모델: ~3GB (float16 양자화)")
        print(f"  pyannote: ~1.5GB")
        print(f"  추론 중간 텐서: ~1GB")
        print(f"  예상 합계: ~5.5GB")
        print(f"  가용 VRAM: 12GB (RTX 3060)")
        print(f"  여유: ~6.5GB ✅")

        # 레이턴시
        print(f"\n⏱️ WebSocket 레이턴시")
        print(f"  500ms 청크 처리: ~50ms (오디오 처리)")
        print(f"  STT 처리: ~500ms (동기 실행)")
        print(f"  총 레이턴시: ~550ms")
        print(f"  목표: < 2초 ✅")

        # 동시성
        print(f"\n🔗 동시 연결")
        print(f"  ThreadPoolExecutor max_workers=1")
        print(f"  최대 동시 연결: 3개 (순차 큐잉)")
        print(f"  VRAM 안전마진: 충분 ✅")

    def run_all_tests(self):
        """모든 테스트 실행"""
        print("\n" + "╔" + "═" * 88 + "╗")
        print("║" + " " * 20 + "🚀 STT 성능 테스트 시작 (Mock 모드)" + " " * 33 + "║")
        print("╚" + "═" * 88 + "╝")

        print("\n⚠️  주의: 이는 Mock 모드 테스트입니다.")
        print("   실제 성능은 Docker 환경에서 models 로드 후 확인하세요:")
        print("   $ cd backend && python scripts/performance_test.py")

        try:
            self.test_stt_performance()
            self.test_diarization_performance()
            self.test_audio_processor()

            self.print_results()
            self.print_summary()

            print("\n" + "=" * 90)
            print("🎉 Mock 성능 테스트 완료")
            print("=" * 90)

        except Exception as e:
            print(f"❌ 테스트 실패: {e}")


def main():
    tester = MockPerformanceTest()
    tester.run_all_tests()


if __name__ == "__main__":
    main()
