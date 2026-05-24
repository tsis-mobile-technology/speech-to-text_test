import logging

logger = logging.getLogger(__name__)

# pynvml 라이브러리가 없는 환경에서도 에러가 발생하지 않도록 폴백 처리
try:
    import pynvml
    pynvml.nvmlInit()
    NVML_AVAILABLE = True
except Exception as e:
    logger.warning(f"Failed to initialize NVML (GPU monitoring): {e}. Running in Mock mode.")
    NVML_AVAILABLE = False

def check_vram_usage() -> tuple[int, int]:
    """
    현재 사용 중인 VRAM과 전체 VRAM 크기를 MB 단위로 반환합니다.
    (사용량, 전체량)
    """
    if not NVML_AVAILABLE:
        # GPU 모니터링이 지원되지 않으면 0, 0 반환 (Mock)
        return 0, 0
        
    try:
        # 0번 GPU의 메모리 정보 쿼리
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        used_mb = int(info.used / (1024 ** 2))
        total_mb = int(info.total / (1024 ** 2))
        return used_mb, total_mb
    except Exception as e:
        logger.error(f"Error querying GPU VRAM usage: {e}")
        return 0, 0

def is_vram_exceeded(threshold_mb: int = 10240) -> bool:
    """
    VRAM 사용량이 임계치(기본 10GB)를 초과했는지 확인합니다.
    """
    used_mb, _ = check_vram_usage()
    if used_mb > threshold_mb:
        return True
    return False

def get_gpu_name() -> str:
    """
    GPU 장치 명칭을 반환합니다.
    """
    if not NVML_AVAILABLE:
        return "No NVIDIA GPU Detected"
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        return pynvml.nvmlDeviceGetName(handle).decode('utf-8') if isinstance(pynvml.nvmlDeviceGetName(handle), bytes) else pynvml.nvmlDeviceGetName(handle)
    except:
        return "Unknown NVIDIA GPU"
