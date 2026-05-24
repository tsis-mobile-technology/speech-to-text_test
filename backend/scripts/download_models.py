import os
import sys
import yaml
from pathlib import Path
from dotenv import load_dotenv

# 환경변수 로드를 위해 상위 디렉토리 참조 추가
current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent
root_dir = backend_dir.parent

load_dotenv(dotenv_path=root_dir / '.env')

try:
    from huggingface_hub import login, snapshot_download
except ImportError:
    print("Error: 'huggingface_hub' package is required. Please install it with 'pip install huggingface-hub'")
    sys.exit(1)

def download_models():
    token = os.getenv("HF_TOKEN")
    if not token:
        print("Error: HF_TOKEN environment variable not set in .env file.")
        sys.exit(1)
        
    print("Logging into Hugging Face...")
    login(token=token)
    
    models_dir = backend_dir / "models"
    models_dir.mkdir(exist_ok=True)
    
    print("\n[1/3] Downloading pyannote/speaker-diarization-3.1...")
    diarization_dir = models_dir / "pyannote" / "speaker-diarization-3.1"
    snapshot_download(
        repo_id="pyannote/speaker-diarization-3.1",
        local_dir=str(diarization_dir),
        ignore_patterns=["*.txt", "*.md"],
        token=token
    )
    
    print("\n[2/3] Downloading pyannote/segmentation-3.0...")
    segmentation_dir = models_dir / "pyannote" / "segmentation-3.0"
    snapshot_download(
        repo_id="pyannote/segmentation-3.0",
        local_dir=str(segmentation_dir),
        ignore_patterns=["*.txt", "*.md"],
        token=token
    )
    
    print("\n[3/3] Downloading Systran/faster-whisper-medium...")
    whisper_dir = models_dir / "whisper" / "faster-whisper-medium"
    snapshot_download(
        repo_id="Systran/faster-whisper-medium",
        local_dir=str(whisper_dir),
        ignore_patterns=["*.md"]
    )
    
    # pyannote 오프라인 로드 패치: config.yaml 파일의 segmentation 참조를 로컬 경로로 수정
    config_yaml_path = diarization_dir / "config.yaml"
    if config_yaml_path.exists():
        print("\nPatching pyannote config.yaml for offline local loading...")
        with open(config_yaml_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            
        # segmentation 모델 참조를 로컬 디렉토리 경로로 업데이트
        if 'pipeline' in config and 'params' in config['pipeline'] and 'segmentation' in config['pipeline']['params']:
            # 상대 경로 혹은 절대 경로로 변경 (컨테이너 내 경로 기준)
            # 여기서는 로컬 파일 로드를 위해 모델 폴더 내 pytorch_model.bin 파일의 절대경로를 동적으로 지정할 수 있도록 로직 구성
            config['pipeline']['params']['segmentation'] = str(segmentation_dir / "pytorch_model.bin")
            
        with open(config_yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False)
        print(f"Patched config.yaml at {config_yaml_path} successfully.")
        
    print("\nAll models downloaded and configured successfully!")

if __name__ == "__main__":
    download_models()
