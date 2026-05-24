import pytest
import uuid
from app.core.pipeline import align_segments
from app.models.transcript import TranscriptSegment

def test_align_segments_basic():
    # 1. 테스트 입력 데이터 구성
    session_id = str(uuid.uuid4())
    
    # Whisper 세그먼트 (텍스트 및 타임스탬프)
    whisper_segments = [
        {"start": 0.5, "end": 2.5, "text": "안녕하세요", "confidence": 0.95},
        {"start": 3.0, "end": 5.0, "text": "반갑습니다", "confidence": 0.90},
        {"start": 5.5, "end": 8.0, "text": "오늘 회의를 시작합니다", "confidence": 0.88}
    ]
    
    # Pyannote 화자 구간 세그먼트
    diarization_segments = [
        {"start": 0.0, "end": 2.8, "speaker": "SPEAKER_00"},
        {"start": 2.9, "end": 5.2, "speaker": "SPEAKER_01"},
        {"start": 5.3, "end": 9.0, "speaker": "SPEAKER_00"}
    ]
    
    # 2. 함수 실행
    aligned = align_segments(whisper_segments, diarization_segments, session_id)
    
    # 3. 검증
    assert len(aligned) == 3
    
    # 각 세그먼트 타입 및 내용 검증
    for seg in aligned:
        assert isinstance(seg, TranscriptSegment)
        assert seg.session_id == session_id
        assert seg.is_final is True
        
    # 시간 오버랩 기준 화자 할당 매칭 검증
    # "안녕하세요" (0.5~2.5) -> 중심점 1.5 -> SPEAKER_00 (0.0~2.8 내 존재)
    assert aligned[0].text == "안녕하세요"
    assert aligned[0].speaker == "SPEAKER_00"
    
    # "반갑습니다" (3.0~5.0) -> 중심점 4.0 -> SPEAKER_01 (2.9~5.2 내 존재)
    assert aligned[1].text == "반갑습니다"
    assert aligned[1].speaker == "SPEAKER_01"
    
    # "오늘 회의를 시작합니다" (5.5~8.0) -> 중심점 6.75 -> SPEAKER_00 (5.3~9.0 내 존재)
    assert aligned[2].text == "오늘 회의를 시작합니다"
    assert aligned[2].speaker == "SPEAKER_00"


def test_align_segments_overlap_fallback():
    # 1차 매칭인 중심점 매칭이 안되는 경계선 상의 경우, 2차 매칭(오버랩 시간 최대값)이 정상 작동하는지 검증
    session_id = str(uuid.uuid4())
    
    # Whisper 세그먼트가 화자 분할 경계에 절반씩 겹쳐 있음
    whisper_segments = [
        {"start": 2.0, "end": 4.0, "text": "경계선 발화", "confidence": 0.85}
    ]
    
    # SPEAKER_00와 1초 겹침 (2.0 ~ 3.0)
    # SPEAKER_01와 0.5초 겹침 (3.0 ~ 3.5)
    diarization_segments = [
        {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
        {"start": 3.0, "end": 3.5, "speaker": "SPEAKER_01"}
    ]
    
    aligned = align_segments(whisper_segments, diarization_segments, session_id)
    
    # 겹치는 시간이 더 긴 SPEAKER_00이 선택되어야 함
    assert aligned[0].speaker == "SPEAKER_00"
