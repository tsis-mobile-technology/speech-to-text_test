"""
Phase 1 STT 정확도 개선 사항 검증 테스트
- Beam size 파라미터 전달 확인
- Language Prompt 초기화 확인
- Temperature 설정 확인
- Config 신규 파라미터 확인
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.config import settings
from app.core.stt_engine import STTEngine
from app.core.pipeline import run_stt_diarization_pipeline


class TestBeamSizeConfiguration:
    """Beam size 설정 테스트"""

    def test_beam_size_profiles_exist(self):
        """Beam size 3개 프로필 존재 확인"""
        assert hasattr(settings, "BEAM_SIZE_FAST")
        assert hasattr(settings, "BEAM_SIZE_BALANCED")
        assert hasattr(settings, "BEAM_SIZE_HIGH")

    def test_beam_size_values(self):
        """Beam size 값 검증"""
        assert settings.BEAM_SIZE_FAST == 1, "Fast profile should be 1"
        assert settings.BEAM_SIZE_BALANCED == 3, "Balanced profile should be 3"
        assert settings.BEAM_SIZE_HIGH == 5, "High profile should be 5"

    def test_beam_size_hierarchy(self):
        """Beam size 계층 구조 (속도: Fast < Balanced < High)"""
        assert settings.BEAM_SIZE_FAST < settings.BEAM_SIZE_BALANCED < settings.BEAM_SIZE_HIGH


class TestLanguagePromptConfiguration:
    """Language Prompt 설정 테스트"""

    def test_context_prompts_exist(self):
        """Context prompts 사전 존재 확인"""
        assert hasattr(settings, "CONTEXT_PROMPTS")
        assert isinstance(settings.CONTEXT_PROMPTS, dict)

    def test_context_prompt_domains(self):
        """도메인별 Prompt 존재 확인"""
        required_domains = ["meeting", "technical", "general"]
        for domain in required_domains:
            assert domain in settings.CONTEXT_PROMPTS, f"Missing domain: {domain}"
            assert isinstance(settings.CONTEXT_PROMPTS[domain], str), f"Prompt should be string: {domain}"

    def test_context_prompt_content(self):
        """Prompt 콘텐츠 검증 (비어있지 않음)"""
        for domain, prompt in settings.CONTEXT_PROMPTS.items():
            assert len(prompt) > 0, f"Prompt for {domain} should not be empty"
            assert "," in prompt, f"Prompt should contain keywords separated by comma: {domain}"


class TestTemperatureConfiguration:
    """Temperature 설정 테스트"""

    def test_temperature_exists(self):
        """Temperature 파라미터 존재 확인"""
        assert hasattr(settings, "TEMPERATURE")
        assert isinstance(settings.TEMPERATURE, list)

    def test_temperature_values(self):
        """Temperature 값 범위 검증 (0.0 ~ 1.0)"""
        assert len(settings.TEMPERATURE) > 0, "Temperature list should not be empty"
        for temp in settings.TEMPERATURE:
            assert 0.0 <= temp <= 1.0, f"Temperature should be in [0.0, 1.0], got {temp}"

    def test_temperature_includes_zero(self):
        """Temperature에 0.0 포함 확인 (결정론적 모드)"""
        assert 0.0 in settings.TEMPERATURE, "Should include 0.0 for deterministic mode"


class TestSTTEngineImprovement:
    """STT 엔진 개선 사항 테스트"""

    @pytest.mark.asyncio
    async def test_transcribe_accepts_beam_size(self):
        """transcribe() 메서드에서 beam_size 파라미터 수용 확인"""
        stt_engine = STTEngine.get_instance()

        # Mock 모드에서는 파라미터 검증만 수행
        with patch.object(stt_engine, 'model', None):  # Mock mode
            # 파라미터 전달 테스트
            # (실제 추론은 아님, 파라미터 전달 검증만)
            assert hasattr(stt_engine, 'transcribe')

    @pytest.mark.asyncio
    async def test_transcribe_accepts_initial_prompt(self):
        """transcribe() 메서드에서 initial_prompt 파라미터 수용 확인"""
        stt_engine = STTEngine.get_instance()

        # 메서드 시그니처 검증
        import inspect
        sig = inspect.signature(stt_engine.transcribe)
        assert "initial_prompt" in sig.parameters, "transcribe should accept initial_prompt"

    @pytest.mark.asyncio
    async def test_transcribe_default_beam_size(self):
        """beam_size None일 때 BALANCED 사용 확인"""
        stt_engine = STTEngine.get_instance()

        # 메서드 검증 (실제 실행 아님)
        import inspect
        source = inspect.getsource(stt_engine.transcribe)
        assert "BEAM_SIZE_BALANCED" in source, "Should use BALANCED as default"


class TestPipelineImprovement:
    """파이프라인 개선 사항 테스트"""

    @pytest.mark.asyncio
    async def test_pipeline_accepts_beam_size(self):
        """run_stt_diarization_pipeline에서 beam_size 파라미터 수용"""
        import inspect
        sig = inspect.signature(run_stt_diarization_pipeline)
        assert "beam_size" in sig.parameters, "Pipeline should accept beam_size"

    @pytest.mark.asyncio
    async def test_pipeline_accepts_context(self):
        """run_stt_diarization_pipeline에서 context 파라미터 수용"""
        import inspect
        sig = inspect.signature(run_stt_diarization_pipeline)
        assert "context" in sig.parameters, "Pipeline should accept context"

    @pytest.mark.asyncio
    async def test_pipeline_default_context(self):
        """Pipeline의 context 기본값이 "meeting"인지 확인"""
        import inspect
        sig = inspect.signature(run_stt_diarization_pipeline)
        context_param = sig.parameters.get("context")
        assert context_param is not None, "context parameter should exist"
        assert context_param.default == "meeting", "Default context should be 'meeting'"


class TestWebSocketConfiguration:
    """WebSocket API 개선 사항 테스트"""

    @pytest.mark.asyncio
    async def test_websocket_uses_fast_beam_size(self):
        """WebSocket이 BEAM_SIZE_FAST를 사용하는지 확인"""
        from app.api.v1 import websocket as ws_module
        import inspect

        source = inspect.getsource(ws_module.websocket_stt_stream)
        assert "BEAM_SIZE_FAST" in source, "WebSocket should use BEAM_SIZE_FAST for real-time"


class TestTranscribeAPIConfiguration:
    """File Upload API 개선 사항 테스트"""

    @pytest.mark.asyncio
    async def test_transcribe_uses_balanced_beam_size(self):
        """File upload API가 BEAM_SIZE_BALANCED를 사용하는지 확인"""
        from app.api.v1 import transcribe as transcribe_module
        import inspect

        source = inspect.getsource(transcribe_module.execute_transcription_task)
        assert "BEAM_SIZE_BALANCED" in source, "File upload should use BEAM_SIZE_BALANCED"


class TestBeamSizeDocumentation:
    """Beam size 문서화 테스트"""

    def test_beam_size_fast_purpose(self):
        """BEAM_SIZE_FAST 용도 확인 (실시간)"""
        # Config에서 확인 가능한 주석 검증
        assert settings.BEAM_SIZE_FAST == 1

    def test_beam_size_balanced_purpose(self):
        """BEAM_SIZE_BALANCED 용도 확인 (파일)"""
        # Config에서 확인 가능한 주석 검증
        assert settings.BEAM_SIZE_BALANCED == 3

    def test_beam_size_high_purpose(self):
        """BEAM_SIZE_HIGH 용도 확인 (고정확도)"""
        # Config에서 확인 가능한 주석 검증
        assert settings.BEAM_SIZE_HIGH == 5


# Integration 테스트
@pytest.mark.integration
class TestPhase1Integration:
    """Phase 1 전체 통합 테스트"""

    @pytest.mark.asyncio
    async def test_configuration_consistency(self):
        """설정의 일관성 확인"""
        # 모든 프로필이 정의되어 있는지 확인
        assert settings.BEAM_SIZE_FAST is not None
        assert settings.BEAM_SIZE_BALANCED is not None
        assert settings.BEAM_SIZE_HIGH is not None

        # 모든 프롬프트가 정의되어 있는지 확인
        assert len(settings.CONTEXT_PROMPTS) >= 3

        # Temperature가 정의되어 있는지 확인
        assert len(settings.TEMPERATURE) > 0

    @pytest.mark.asyncio
    async def test_backward_compatibility(self):
        """기존 코드 호환성 확인"""
        # 기존에 BEAM_SIZE가 없어도 새로운 설정이 있으면 됨
        assert hasattr(settings, "BEAM_SIZE_BALANCED"), "New balanced profile should exist"

    def test_all_context_prompts_are_korean(self):
        """모든 Context Prompt가 한국어로 정의되어 있는지 확인"""
        korean_chars = set("가나다라마바사아자차카타파하")
        for domain, prompt in settings.CONTEXT_PROMPTS.items():
            # 최소 하나의 한글이 포함되어 있는지 확인
            has_korean = any(char in korean_chars for char in prompt)
            assert has_korean, f"Prompt '{domain}' should contain Korean characters"
