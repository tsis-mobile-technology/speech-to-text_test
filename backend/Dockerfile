# GPU 가속이 미리 정의된 PyTorch 공식 런타임 이미지를 기본 이미지로 채택
FROM pytorch/pytorch:2.2.2-cuda12.1-cudnn8-runtime

WORKDIR /app

# 타임존 대화형 질문 무시 설정
ENV DEBIAN_FRONTEND=noninteractive

# ffmpeg 및 soundfile 라이브러리에 필요한 libsndfile1 필수 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    build-essential \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt 복사 및 파이이썬 의존성 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 및 스크립트 디렉토리 구조 복사
COPY app/ ./app/
COPY scripts/ ./scripts/

# 컨테이너 내 모델이 저장될 디렉토리 생성
RUN mkdir -p /app/models

# 8000 포트 개방
EXPOSE 8000

# FastAPI 백엔드 서비스 실행
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
