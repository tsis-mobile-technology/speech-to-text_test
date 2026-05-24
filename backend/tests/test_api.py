import pytest
import os
import tempfile
import numpy as np
import scipy.io.wavfile as wavfile
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

@pytest.fixture
def temp_audio_file():
    """
    1초 분량의 16kHz Mono WAV 파일을 생성합니다.
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


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    json_data = response.json()
    assert "project" in json_data
    assert "api_documentation" in json_data
    assert "health_check" in json_data


def test_health_endpoints():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    
    response_gpu = client.get("/api/v1/health/gpu")
    assert response_gpu.status_code == 200
    json_gpu = response_gpu.json()
    assert "vram_used_mb" in json_gpu
    assert "vram_total_mb" in json_gpu


def test_transcribe_upload_api(temp_audio_file):
    # 1. 파일 전송 요청
    with open(temp_audio_file, "rb") as audio:
        response = client.post(
            "/api/v1/transcribe",
            files={"audio_file": (os.path.basename(temp_audio_file), audio, "audio/wav")},
            data={"enable_diarization": "false"}
        )
        
    # 2. 비동기 작업 접수 상태 검증
    assert response.status_code in [200, 202]
    json_data = response.json()
    assert "session_id" in json_data
    assert "status" in json_data
    
    session_id = json_data["session_id"]
    
    # 3. 세션 조회 API 검증
    response_session = client.get(f"/api/v1/sessions/{session_id}")
    assert response_session.status_code == 200
    session_data = response_session.json()
    assert session_data["session_id"] == session_id
    assert "status" in session_data
    assert "segments" in session_data


def test_websocket_stream_connection():
    # WebSocket 연결 및 기본 프로토콜 테스트
    with client.websocket_connect("/api/v1/ws/stream") as websocket:
        # 연결이 잘 체결되었는지와 첫 메시지가 올바르게 처리되는지
        # 1초 분량의 16kHz PCM Float32 바이트 데이터 송신 시뮬레이션
        # 16000 samples * 4 bytes = 64000 bytes
        dummy_pcm = np.zeros(8000, dtype=np.float32).tobytes() # 500ms chunk
        
        websocket.send_bytes(dummy_pcm)
        
        # 스트리밍 응답 대기 (Non-blocking 형식으로 대기 또는 timeout 설정)
        try:
            # 첫 번째 수신된 텍스트 메시지 확인 (partial 또는 config 등)
            response = websocket.receive_json()
            assert "type" in response
            assert "session_id" in response
        except Exception as e:
            pytest.fail(f"WebSocket communication failed: {e}")
