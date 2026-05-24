import os
import subprocess
import tempfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def convert_to_wav_16k_mono(input_path: str) -> str:
    """
    임의의 오디오 파일을 faster-whisper 및 pyannote 처리에 적합한
    16kHz, Mono, 16-bit PCM WAV 포맷으로 변환하여 임시 파일 경로를 반환합니다.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input audio file not found: {input_path}")
        
    temp_dir = tempfile.gettempdir()
    output_filename = f"processed_{os.path.basename(input_path)}.wav"
    output_path = os.path.join(temp_dir, output_filename)
    
    # 이미 해당 임시 파일이 존재하면 먼저 삭제
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass

    # ffmpeg를 실행하여 16kHz mono WAV 파일로 리샘플링
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_path
    ]
    
    logger.info(f"Converting audio using ffmpeg: {' '.join(cmd)}")
    try:
        # stdout/stderr를 캡처하여 오류 기록
        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        logger.info(f"Audio conversion completed successfully. Result saved to {output_path}")
        return output_path
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(f"Failed to run ffmpeg. Standard resampling fallback: {e}")
        # ffmpeg가 설치되어 있지 않거나 변환 실패한 경우, 원본 오디오 경로를 그냥 반환하여 모델 라이브러리가 직접 파싱하도록 유도
        # (faster-whisper와 pyannote 내부에 오디오 디코딩 기능이 내장되어 있어 가끔 fallback 가능)
        return input_path

def get_audio_duration(audio_path: str) -> float:
    """
    ffprobe를 호출하거나 또는 오디오 파일을 검사하여 총 재생 시간(초)을 구합니다.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True)
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"Failed to get audio duration using ffprobe: {e}")
        # ffprobe가 없을 경우 대략적인 추정치나 0.0을 반환
        try:
            import soundfile as sf
            info = sf.info(audio_path)
            return info.duration
        except ImportError:
            # soundfile 마저도 없으면 0.0 반환
            return 0.0
