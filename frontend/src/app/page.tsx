'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useAudioCapture } from '@/hooks/useAudioCapture';
import { useWebSocket } from '@/hooks/useWebSocket';
import { Mic, Square, AlertCircle, HardDrive, Clock, ChevronRight, Activity, Keyboard } from 'lucide-react';
import Link from 'next/link';

interface Segment {
  id: string;
  start: number;
  end: number;
  text: string;
  speaker: string;
  confidence: number;
  is_final: boolean;
}

export default function RealtimeMeetingPage() {
  const [segments, setSegments] = useState<Segment[]>([]);
  const [partialSegment, setPartialSegment] = useState<Segment | null>(null);
  const [gpuUsage, setGpuUsage] = useState<number>(0);
  const [completedSessionId, setCompletedSessionId] = useState<string | null>(null);
  
  // 브라우저 뷰포트 스크롤 및 캔버스 관련 refs
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationRef = useRef<number | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);

  // WebSocket 메시지 수신 핸들러 (기능 무손실 보존)
  const handleWebSocketMessage = useCallback((data: any) => {
    if (!data || typeof data !== 'object') {
      console.warn('⚠️ Invalid message data:', data);
      return;
    }

    const messageType = data.type;
    console.log('🎯 WebSocket message:', messageType);

    try {
      if (messageType === 'partial' && data.segment) {
        if (!data.segment.text || data.segment.text.trim().length === 0) {
          console.debug('⊘ Skipping empty partial segment');
          return;
        }

        console.log('✅ partial:', data.segment.text.substring(0, 30));
        setPartialSegment(data.segment);

        if (data.gpu_usage_mb !== undefined && data.gpu_usage_mb !== null) {
          setGpuUsage(data.gpu_usage_mb);
        }
      } else if (messageType === 'final' && data.segment) {
        if (!data.segment || !data.segment.id) {
          console.warn('⚠️ Final segment missing required fields');
          return;
        }

        if (!data.segment.text || data.segment.text.trim().length === 0) {
          console.debug('⊘ Skipping empty final segment');
          return;
        }

        console.log('✅ final:', data.segment.text.substring(0, 30));

        if (data.gpu_usage_mb !== undefined && data.gpu_usage_mb !== null) {
          setGpuUsage(data.gpu_usage_mb);
        }

        setSegments((prev) => {
          if (prev.some((s) => s.id === data.segment.id)) {
            console.log('⊘ Duplicate segment ignored:', data.segment.id);
            return prev;
          }
          return [...prev, data.segment];
        });

        setPartialSegment(null);
      } else if (messageType === 'speaker_updated') {
        console.log('🎤 speaker_updated:', data.segments?.length ?? 0, 'segments');

        if (data.segments && Array.isArray(data.segments)) {
          if (data.segments.length > 0) {
            setSegments(data.segments);
          }
        }

        if (data.session_id) {
          setCompletedSessionId(data.session_id);
        }
      } else if (messageType === 'error') {
        console.error('❌ Server error:', data.error);
      }
    } catch (err) {
      console.error('❌ Error processing WebSocket message:', err);
    }
  }, []);

  // 백엔드 WS 주소 산출
  const [wsUrl, setWsUrl] = useState('ws://localhost:8000/api/v1/ws/stream');
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const host = window.location.hostname;
      setWsUrl(`ws://${host}:8000/api/v1/ws/stream`);
    }
  }, []);

  // WebSocket 커스텀 훅 바인딩
  const {
    isConnected,
    error: wsError,
    connect: wsConnect,
    disconnect: wsDisconnect,
    sendAudioChunk,
  } = useWebSocket({
    url: wsUrl,
    onMessage: handleWebSocketMessage,
    onClose: () => {
      stopRecording();
    }
  });

  // 오디오 캡처 커스텀 훅 바인딩
  const {
    isRecording,
    error: audioError,
    startRecording,
    stopRecording,
    audioContext,
    mediaStream,
  } = useAudioCapture({
    onAudioChunk: sendAudioChunk,
  });

  // 녹음 시작
  const handleStart = async () => {
    setCompletedSessionId(null);
    setSegments([]);
    setPartialSegment(null);

    try {
      console.log('🎤 마이크 캡처 시작...');
      await startRecording();
      console.log('🔌 WebSocket 연결 요청...');
      wsConnect();
    } catch (err) {
      console.error('❌ 녹음 시작 실패:', err);
    }
  };

  // 녹음 정지
  const handleStop = async () => {
    await stopRecording();
    wsDisconnect();
  };

  // 주파수 파형 그리기 로직 (네온 링 및 플랙시블 오디오 파동 개선)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let bufferLength = 0;
    let dataArray = new Uint8Array(0);
    let analyser: AnalyserNode | null = null;

    if (isRecording && audioContext && mediaStream) {
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 128; // 더 부드러운 반응성
      const source = audioContext.createMediaStreamSource(mediaStream);
      source.connect(analyser);
      analyserRef.current = analyser;
      bufferLength = analyser.frequencyBinCount;
      dataArray = new Uint8Array(bufferLength);
    }

    let waveOffset = 0;
    const draw = () => {
      animationRef.current = requestAnimationFrame(draw);
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      if (isRecording && analyser) {
        analyser.getByteFrequencyData(dataArray);
        
        // 실시간 음성 네온 주파수 파동 그리기
        const barWidth = (canvas.width / bufferLength) * 1.5;
        let x = 0;

        for (let i = 0; i < bufferLength; i++) {
          const value = dataArray[i];
          const percent = value / 255;
          const height = canvas.height * percent * 0.85;

          // 그라데이션 선 설정
          const gradient = ctx.createLinearGradient(0, canvas.height, 0, 0);
          gradient.addColorStop(0, 'rgba(99, 102, 241, 0.1)'); // Indigo
          gradient.addColorStop(0.5, 'rgba(168, 85, 247, 0.8)'); // Purple
          gradient.addColorStop(1, '#14b8a6'); // Teal

          ctx.fillStyle = gradient;
          // 중심축 기준으로 위아래 대칭형 주파수 렌더링
          const yPos = (canvas.height - height) / 2;
          ctx.beginPath();
          ctx.roundRect(x, yPos, barWidth - 3, height, 4);
          ctx.fill();

          x += barWidth;
        }
      } else {
        // 비녹음 시 네온 대기 Sine 파동 시뮬레이션
        ctx.beginPath();
        ctx.strokeStyle = 'rgba(99, 102, 241, 0.3)';
        ctx.lineWidth = 2;
        
        const points: number[] = [];
        waveOffset += 0.05;

        for (let i = 0; i < canvas.width; i++) {
          const y = canvas.height / 2 + Math.sin(i * 0.02 + waveOffset) * 6;
          if (i === 0) {
            ctx.moveTo(i, y);
          } else {
            ctx.lineTo(i, y);
          }
        }
        ctx.stroke();
      }
    };

    draw();

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [isRecording, audioContext, mediaStream]);

  // 새로운 자막이 추가될 때 부드럽게 스크롤
  useEffect(() => {
    if (transcriptEndRef.current) {
      transcriptEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [segments, partialSegment]);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: '30px' }} style={{ contentVisibility: 'auto' }}>
      
      {/* 좌측: 실시간 자막 타임라인 뷰 */}
      <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 190px)' }}>
        
        {/* 상단바 컨트롤 영역 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
          <div>
            <span className="gradient-text" style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Live Recording Room
            </span>
            <h1 style={{ fontSize: '2.25rem', marginTop: '4px', fontWeight: 800 }}>실시간 회의록 작성</h1>
          </div>
          
          <div style={{ display: 'flex', gap: '12px' }}>
            {!isRecording ? (
              <button onClick={handleStart} className="btn btn-primary" style={{ padding: '14px 32px', borderRadius: '9999px' }}>
                <Mic size={18} />
                회의 시작
              </button>
            ) : (
              <button onClick={handleStop} className="btn btn-danger mic-active" style={{ padding: '14px 32px', borderRadius: '9999px' }}>
                <Square size={18} />
                회의 종료
              </button>
            )}
          </div>
        </div>

        {/* 에러 피드백 */}
        {(wsError || audioError) && (
          <div className="glass-panel" style={{
            padding: '16px 20px',
            backgroundColor: 'rgba(239, 68, 68, 0.08)',
            borderColor: 'rgba(239, 68, 68, 0.25)',
            borderRadius: 'var(--radius-sm)',
            marginBottom: '20px',
            display: 'flex',
            alignItems: 'center',
            gap: '12px'
          }}>
            <AlertCircle color="#ef4444" size={20} />
            <span style={{ fontSize: '0.9rem', color: '#fca5a5', fontWeight: 500 }}>
              {wsError || audioError}
            </span>
          </div>
        )}

        {/* 메인 자막 타임라인 패널 */}
        <div className="glass-panel" style={{
          flex: 1,
          padding: '30px',
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: '24px',
          maxHeight: 'calc(100vh - 380px)',
          background: 'rgba(15, 17, 26, 0.45)',
          borderWidth: isRecording ? '1px' : '1px',
          borderColor: isRecording ? 'rgba(99, 102, 241, 0.25)' : 'var(--border-light)',
          boxShadow: isRecording ? 'inset 0 0 40px rgba(99, 102, 241, 0.05)' : 'none'
        }}>
          {segments.length === 0 && !partialSegment && (
            <div style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-muted)',
              textAlign: 'center',
              padding: '60px 40px'
            }}>
              <div style={{
                width: '80px',
                height: '80px',
                borderRadius: '50%',
                background: 'rgba(255,255,255,0.02)',
                border: '1px solid var(--border-light)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '20px',
                animation: isRecording ? 'pulseGlow 2s infinite' : 'none'
              }}>
                <Mic size={36} style={{ color: isRecording ? 'var(--color-primary)' : 'var(--text-muted)', opacity: isRecording ? 1 : 0.4 }} />
              </div>
              <p style={{ fontSize: '1.2rem', fontWeight: 700, color: 'white' }}>
                {isRecording ? '목소리를 인식하기 위해 대기 중입니다...' : '마이크 회의 시작 버튼을 클릭해 주세요'}
              </p>
              <p style={{ fontSize: '0.85rem', marginTop: '8px', maxWidth: '360px', lineHeight: '1.5' }}>
                로컬 Silero VAD로 침묵을 필터링하고 CTranslate2 엔진이 실시간 한글 문장 단위로 분할하여 전사합니다.
              </p>
            </div>
          )}

          {/* 자막 리스트 타임라인 */}
          <div className="chat-bubble-container">
            {segments.map((seg) => {
              const spkIndex = parseInt(seg.speaker.replace(/[^0-9]/g, '')) % 4 || 0;
              const badgeClass = `speaker-badge spk-${spkIndex}`;
              
              return (
                <div key={seg.id} className="chat-row" style={{ width: '100%', maxWidth: '100%', marginBottom: '16px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', width: '100%' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span className={badgeClass}>{seg.speaker}</span>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 500 }}>
                        {seg.start.toFixed(1)}초 - {seg.end.toFixed(1)}초
                      </span>
                      {seg.confidence > 0 && (
                        <span style={{ 
                          fontSize: '0.7rem', 
                          padding: '2px 6px', 
                          borderRadius: '4px',
                          backgroundColor: seg.confidence >= 0.90 ? 'rgba(20, 184, 166, 0.08)' : 'rgba(245, 158, 11, 0.08)',
                          color: seg.confidence >= 0.90 ? '#2dd4bf' : '#fbbf24',
                          border: '1px solid transparent',
                          borderColor: seg.confidence >= 0.90 ? 'rgba(20, 184, 166, 0.15)' : 'rgba(245, 158, 11, 0.15)'
                        }}>
                          신뢰도 {Math.round(seg.confidence * 100)}%
                        </span>
                      )}
                    </div>
                    <div className="chat-bubble" style={{ 
                      maxWidth: '90%', 
                      borderTopLeftRadius: '0px', 
                      background: 'rgba(255, 255, 255, 0.025)',
                      borderLeft: '2.5px solid var(--color-primary)'
                    }}>
                      <p style={{ fontSize: '1.05rem', color: 'white', fontWeight: 500 }}>{seg.text}</p>
                    </div>
                  </div>
                </div>
              );
            })}

            {/* 실시간 부분 자막(수신중) 피드백 */}
            {partialSegment && (
              <div className="chat-row" style={{ width: '100%', opacity: 0.75, marginBottom: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', width: '100%' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span className="speaker-badge spk-generic" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                      <span className="pulsing-dot" style={{ width: '6px', height: '6px', backgroundColor: 'var(--text-secondary)' }}></span>
                      연산중
                    </span>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {partialSegment.start.toFixed(1)}초~
                    </span>
                  </div>
                  <div className="chat-bubble" style={{ 
                    maxWidth: '85%', 
                    borderTopLeftRadius: '0px', 
                    background: 'rgba(255, 255, 255, 0.01)',
                    borderLeft: '2.5px dashed var(--text-muted)'
                  }}>
                    <p style={{ fontSize: '1.05rem', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
                      {partialSegment.text}...
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div ref={transcriptEndRef} />
        </div>
      </div>

      {/* 우측 사이드 바: 비주얼라이저 및 모니터 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
        
        {/* 마이크 입력부 데시벨 모니터 */}
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Activity size={18} className="gradient-text" />
            <h3 style={{ fontSize: '1.05rem', fontWeight: 700 }}>실시간 오디오 스펙트럼</h3>
          </div>
          
          <div style={{
            width: '100%',
            height: '110px',
            backgroundColor: 'rgba(0,0,0,0.3)',
            borderRadius: 'var(--radius-sm)',
            overflow: 'hidden',
            border: '1px solid var(--border-light)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            position: 'relative'
          }}>
            <canvas ref={canvasRef} width="290" height="110" style={{ width: '100%', height: '100%' }} />
            {!isRecording && (
              <span style={{ position: 'absolute', color: 'var(--text-muted)', fontSize: '0.8rem', fontWeight: 500, letterSpacing: '0.05em' }}>
                AUDIO FEED DISCONNECTED
              </span>
            )}
          </div>
        </div>

        {/* GPU 모니터 위젯 */}
        <div className="glass-panel" style={{ padding: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
            <HardDrive size={18} className="gradient-text" />
            <h3 style={{ fontSize: '1.05rem', fontWeight: 700 }}>GPU VRAM 실시간 모니터</h3>
          </div>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '6px' }}>
                <span style={{ color: 'var(--text-secondary)' }}>VRAM 점유율</span>
                <strong style={{ color: 'white' }}>{gpuUsage >= 0 ? `${gpuUsage} MB` : '대기중'}</strong>
              </div>
              <div style={{ width: '100%', height: '6px', backgroundColor: 'rgba(255,255,255,0.04)', borderRadius: '3px', overflow: 'hidden' }}>
                <div style={{
                  width: `${Math.min((gpuUsage / 12000) * 100, 100)}%`,
                  height: '100%',
                  background: 'var(--gradient-neon)',
                  transition: 'width 0.4s cubic-bezier(0.4, 0, 0.2, 1)'
                }}></div>
              </div>
            </div>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: 'var(--text-muted)', borderTop: '1px solid var(--border-light)', paddingTop: '10px', marginTop: '4px' }}>
              <span>GPU 모델</span>
              <span style={{ color: 'white', fontWeight: 600 }}>GeForce RTX 3060</span>
            </div>
          </div>
        </div>

        {/* Diarization(화자 분리) 감지 팝업 패널 */}
        {completedSessionId && (
          <div className="glass-panel" style={{
            padding: '24px',
            background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.12) 0%, rgba(168, 85, 247, 0.12) 100%)',
            borderColor: 'rgba(99, 102, 241, 0.4)',
            boxShadow: '0 8px 30px rgba(99, 102, 241, 0.2)',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
            animation: 'pulseGlow 2s infinite'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Clock size={18} color="#c084fc" />
              <h4 style={{ fontSize: '1rem', color: 'white', fontWeight: 700 }}>화자 분리 매핑 완료</h4>
            </div>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: '1.4' }}>
              pyannote 신경망 파이프라인 분석이 성공적으로 마무리되었습니다. 지금 즉시 정렬된 편집기에서 최종 회의록을 확인하세요.
            </p>
            <Link href={`/sessions/${completedSessionId}`} className="btn btn-primary" style={{
              padding: '10px 20px',
              fontSize: '0.85rem',
              borderRadius: '9999px',
              textDecoration: 'none',
              marginTop: '4px',
              justifyContent: 'center'
            }}>
              상세 회의록 보러가기
              <ChevronRight size={14} />
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
