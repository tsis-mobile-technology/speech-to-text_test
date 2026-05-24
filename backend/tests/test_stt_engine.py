import pytest
import os
import tempfile
import numpy as np
import scipy.io.wavfile as wavfile
from app.core.stt_engine import STTEngine, WHISPER_AVAILABLE

@pytest.fixture
def temp_audio_file():
    """
    1초 분량의 16kHz Mono 440Hz 사인파 오디오 파일을 임시로 생성합니다.
    """
    sample_rate = 16000
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    # 440Hz A4 pitch sine wave
    audio_data = np.sin(2 * np.pi * 440 * t)
    # float32 pcm 정규화
    audio_data = (audio_data * 32767).astype(np.int16)
    
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        temp_path = f.name
        
    wavfile.write(temp_path, sample_rate, audio_data)
    yield temp_path
    
    # 테스트 종료 후 임시 파일 정리
    if os.path.exists(temp_path):
        os.remove(temp_path)


def test_stt_engine_singleton():
    engine1 = STTEngine.get_instance()
    engine2 = STTEngine.get_instance()
    assert engine1 is engine2


@pytest.mark.asyncio
async def test_stt_transcribe(temp_audio_file):
    engine = STTEngine.get_instance()
    
    # 1. 전사 실행
    results = await engine.transcribe(temp_audio_file)
    
    # 2. 결과 검증
    assert isinstance(results, list)
    
    # 결과 포맷 검증
    for segment in results:
        assert "start" in segment
        assert "end" in segment
        assert "text" in segment
        assert "confidence" in segment
        
        assert isinstance(segment["start"], (int, float))
        assert isinstance(segment["end"], (int, float))
        assert isinstance(segment["text"], str)
        assert isinstance(segment["confidence"], (int, float))
        
        # 기본 시간 관계 검증
        assert segment["start"] >= 0
        assert segment["end"] >= segment["start"]
        
    if not WHISPER_AVAILABLE and len(results) > 0:
        # Mock 작동 시 특정 가짜 텍스트를 담고 있는지 확인
        assert "[Mock]" in results[0]["text"]
