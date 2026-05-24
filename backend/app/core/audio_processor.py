import numpy as np
import collections

class AudioBufferProcessor:
    """
    실시간 스트리밍으로 유입되는 PCM 오디오 데이터를 관리하고,
    데시벨(RMS) 에너지 기반의 경량 VAD를 통해 무음/발화 구간 및 추론 시점을 판단합니다.
    """
    def __init__(self, sample_rate: int = 16000, max_duration_sec: int = 30):
        self.sample_rate = sample_rate
        # 최대 30초 분량의 오디오만 슬라이딩 윈도우로 유지 (메모리 폭증 방지)
        self.max_samples = sample_rate * max_duration_sec
        self.buffer = np.zeros(0, dtype=np.float32)
        
        # VAD 판단을 위한 버퍼 및 파라미터 (프레임 크기 30ms = 480 샘플)
        self.frame_size = int(sample_rate * 0.03)
        # 에너지 임계값 더 낮춤 (더 민감하게 음성 감지)
        self.energy_threshold = 0.015  # 발화 여부 에너지 임계값 (노이즈 무시)
        self.silence_limit_frames = int(0.5 / 0.03)  # 0.5초 무음 시 발화 종료로 판단 (빠른 반응)
        
        self.silent_frames_count = 0
        self.is_speaking = False
        self.speaking_frames_count = 0  # 연속 음성 프레임 수

    def append_chunk(self, raw_bytes: bytes) -> bool:
        """
        바이너리 바이트(Float32 PCM) 데이터를 수신하여 numpy 배열로 디코딩하고 버퍼에 누적합니다.
        새로운 발화 마감(VAD trigger)이 일어났을 때 True를 반환합니다.
        """
        # Float32 바이너리를 numpy array로 변환
        chunk = np.frombuffer(raw_bytes, dtype=np.float32)
        if len(chunk) == 0:
            return False
            
        # 디버깅 오디오 신호 분석 로그 추가
        import logging
        db_logger = logging.getLogger("app.core.audio_processor")
        if len(chunk) > 0:
            db_logger.info(f"[Audio Debug] chunk_len={len(chunk)}, max={float(np.max(chunk)):.6f}, min={float(np.min(chunk)):.6f}, mean={float(np.mean(chunk)):.6f}")
            
        # 기존 버퍼에 결합
        self.buffer = np.concatenate((self.buffer, chunk))
        
        # 슬라이딩 윈도우 유지
        if len(self.buffer) > self.max_samples:
            self.buffer = self.buffer[-self.max_samples:]
            
        # 경량 VAD 로직 실행 (단순 RMS 계산)
        # 새로 들어온 청크에 대해 30ms 프레임 단위로 쪼개어 에너지 검사
        trigger_transcription = False
        num_frames = len(chunk) // self.frame_size
        
        for i in range(num_frames):
            frame = chunk[i * self.frame_size : (i + 1) * self.frame_size]
            rms = np.sqrt(np.mean(frame**2)) if len(frame) > 0 else 0
            
            if rms < self.energy_threshold:
                self.silent_frames_count += 1
                if self.is_speaking and self.silent_frames_count >= self.silence_limit_frames:
                    # 말하다가 무음 임계시간 돌파 -> 자막 확정(transcription) 트리거!
                    self.is_speaking = False
                    self.speaking_frames_count = 0
                    trigger_transcription = True
            else:
                self.silent_frames_count = 0
                self.is_speaking = True
                self.speaking_frames_count += 1
                # 3초 이상 계속 말하면 실시간 처리 (partial 결과 빠르게 전송)
                if self.speaking_frames_count >= int(3.0 / 0.03):
                    trigger_transcription = True
                    self.speaking_frames_count = 0  # 카운터 리셋

        return trigger_transcription

    def get_audio_data(self) -> np.ndarray:
        """
        현재 버퍼에 있는 오디오 넘파이 배열 데이터를 반환합니다.
        """
        return self.buffer

    def clear(self):
        """
        버퍼를 완전히 리셋합니다.
        """
        self.buffer = np.zeros(0, dtype=np.float32)
        self.silent_frames_count = 0
        self.is_speaking = False
        self.speaking_frames_count = 0
