import pytest
import os
import tempfile
import numpy as np
import scipy.io.wavfile as wavfile
from app.core.diarization import DiarizationEngine, PYANNOTE_AVAILABLE

@pytest.fixture
def temp_audio_file():
    """
    1초 분량의 16kHz Mono 440Hz 사인파 오디오 파일을 임시로 생성합니다.
    """
    sample_rate = 16000
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    audio_data = np.sin(2 * np.pi * 440 * t)
    audio_data = (audio_data * 32767).astype(np.int16)
    
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        temp_path = f.name
        
    wavfile.write(temp_path, sample_rate, audio_data)
    yield temp_path
    
    if os.path.exists(temp_path):
        os.remove(temp_path)


def test_diarization_engine_singleton():
    engine1 = DiarizationEngine.get_instance()
    engine2 = DiarizationEngine.get_instance()
    assert engine1 is engine2


@pytest.mark.asyncio
async def test_diarization_run(temp_audio_file):
    engine = DiarizationEngine.get_instance()
    
    # 1. 화자분리 실행
    results = await engine.diarize(temp_audio_file)
    
    # 2. 결과 검증
    assert isinstance(results, list)
    assert len(results) > 0
    
    # 결과 포맷 검증
    for segment in results:
        assert "start" in segment
        assert "end" in segment
        assert "speaker" in segment
        
        assert isinstance(segment["start"], (int, float))
        assert isinstance(segment["end"], (int, float))
        assert isinstance(segment["speaker"], str)
        assert segment["speaker"].startswith("SPEAKER_")
        
        # 시간 관계 검증
        assert segment["start"] >= 0
        assert segment["end"] >= segment["start"]
