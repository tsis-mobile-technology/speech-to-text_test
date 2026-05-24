'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useAudioCapture } from '@/hooks/useAudioCapture';
import { useWebSocket } from '@/hooks/useWebSocket';
import { Mic, Square, AlertCircle, HardDrive, Clock, ChevronRight } from 'lucide-react';
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
  
  // 브라우저 뷰포트 스크롤 제어용
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationRef = useRef<number | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);

  // WebSocket 메시지 수신 핸들러
  const handleWebSocketMessage = useCallback((data: any) => {
    if (data.type === 'partial' && data.segment) {
      setPartialSegment(data.segment);
      if (data.gpu_usage_mb) setGpuUsage(data.gpu_usage_mb);
    } else if (data.type === 'final' && data.segment) {
      setSegments((prev) => {
        // 이미 들어온 세그먼트 ID면 중복 추가 방지
        if (prev.some((s) => s.id === data.segment.id)) return prev;
        return [...prev, data.segment];
      });
      setPartialSegment(null);
    } else if (data.type === 'speaker_updated') {
      // 최종 화자 매핑 리스트가 내려왔을 때
      if (data.segments) {
        setSegments(data.segments);
      }
      setCompletedSessionId(data.session_id);
    }
  }, []);

  // 백엔드 WS 주소 산출 (개발 모드 고려)
  const [wsUrl, setWsUrl] = useState('ws://localhost:8000/api/v1/ws/stream');
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const host = window.location.hostname;
      // 로컬이나 도커 환경에 유연하게 접속
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
      // 닫힐 때 마이크도 종료
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

  // 녹음 시작 버튼 핸들러
  const handleStart = async () => {
    setCompletedSessionId(null);
    setSegments([]);
    setPartialSegment(null);

    try {
      console.log('🎤 handleStart: 마이크 캡처 시작 중...');
      // 1. 마이크 캡처 먼저 시작 (권한 확인용)
      await startRecording();
      console.log('✅ handleStart: 마이크 캡처 성공');

      // 2. 마이크 캡처 성공 후 WebSocket 연결
      console.log('🔌 handleStart: WebSocket 연결 중...');
      wsConnect();
      console.log('✅ handleStart: WebSocket 연결 요청 완료');
    } catch (err) {
      console.error('❌ handleStart 에러:', err);
    }
  };

  // 녹음 정지 버튼 핸들러
  const handleStop = async () => {
    await stopRecording();
    wsDisconnect();
  };

  // 말할 때 파형(Visualizer) 그리기 로직
  useEffect(() => {
    if (isRecording && audioContext && mediaStream && canvasRef.current) {
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      const source = audioContext.createMediaStreamSource(mediaStream);
      source.connect(analyser);
      analyserRef.current = analyser;

      const canvas = canvasRef.current;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const draw = () => {
        animationRef.current = requestAnimationFrame(draw);
        analyser.getByteFrequencyData(dataArray);

        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        // 현대적인 네온 파형 바 그리기
        const barWidth = (canvas.width / bufferLength) * 2.5;
        let barHeight;
        let x = 0;

        for (let i = 0; i < bufferLength; i++) {
          barHeight = dataArray[i] / 2.5;

          const gradient = ctx.createLinearGradient(0, canvas.height, 0, 0);
          gradient.addColorStop(0, '#6366f1');
          gradient.addColorStop(0.5, '#a855f7');
          gradient.addColorStop(1, '#14b8a6');

          ctx.fillStyle = gradient;
          ctx.fillRect(x, canvas.height - barHeight, barWidth - 2, barHeight);

          x += barWidth;
        }
      };

      draw();
    } else {
      // 녹음이 꺼져있을 때 가짜 대기선 애니메이션
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
      const canvas = canvasRef.current;
      if (canvas) {
        const ctx = canvas.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
    }

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [isRecording, audioContext, mediaStream]);

  // 새로운 자막이 추가될 때 스크롤 포커싱
  useEffect(() => {
    if (transcriptEndRef.current) {
      transcriptEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [segments, partialSegment]);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: '30px' }}>
      {/* 좌측: 실시간 자막 타임라인 뷰 */}
      <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 200px)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
          <div>
            <span className="gradient-text" style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Live Session
            </span>
            <h1 style={{ fontSize: '2rem', marginTop: '4px' }}>실시간 회의록 작성</h1>
          </div>
          
          <div style={{ display: 'flex', gap: '12px' }}>
            {!isRecording ? (
              <button onClick={handleStart} className="btn btn-primary" style={{ padding: '12px 28px', borderRadius: '9999px' }}>
                <Mic size={18} />
                회의 시작
              </button>
            ) : (
              <button onClick={handleStop} className="btn btn-danger" style={{ padding: '12px 28px', borderRadius: '9999px' }}>
                <Square size={18} />
                회의 종료
              </button>
            )}
          </div>
        </div>

        {/* 에러 패널 */}
        {(wsError || audioError) && (
          <div className="glass-panel" style={{
            padding: '16px 20px',
            backgroundColor: 'rgba(239, 68, 68, 0.1)',
            borderColor: 'rgba(239, 68, 68, 0.2)',
            borderRadius: 'var(--radius-sm)',
            marginBottom: '20px',
            display: 'flex',
            alignItems: 'center',
            gap: '12px'
          }}>
            <AlertCircle color="#ef4444" size={20} />
            <span style={{ fontSize: '0.9rem', color: '#fca5a5' }}>
              {wsError || audioError}
            </span>
          </div>
        )}

        {/* 자막 스트리밍 영역 */}
        <div className="glass-panel" style={{
          flex: 1,
          padding: '30px',
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: '24px',
          maxHeight: 'calc(100vh - 380px)'
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
              padding: '40px'
            }}>
              <Mic size={48} style={{ marginBottom: '16px', opacity: 0.3 }} />
              <p style={{ fontSize: '1.1rem', fontWeight: 600 }}>회의 시작 버튼을 누르고 말씀해 주세요.</p>
              <p style={{ fontSize: '0.85rem', marginTop: '8px' }}>음성이 무음 VAD 필터를 거쳐 실시간으로 이곳에 표현됩니다.</p>
            </div>
          )}

          {/* 확정된 전사 자막 목록 */}
          {segments.map((seg) => {
            const spkIndex = parseInt(seg.speaker.replace(/[^0-9]/g, '')) % 4 || 0;
            const badgeClass = `speaker-badge spk-${spkIndex}`;
            
            return (
              <div key={seg.id} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span className={badgeClass}>{seg.speaker}</span>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {seg.start.toFixed(1)}s - {seg.end.toFixed(1)}s
                  </span>
                </div>
                <p style={{ fontSize: '1.05rem', color: 'var(--text-primary)', paddingLeft: '4px' }}>
                  {seg.text}
                </p>
              </div>
            );
          })}

          {/* 실시간 말하고 있는 부분자막(Partial) */}
          {partialSegment && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', opacity: 0.6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <span className="speaker-badge spk-generic">수신중</span>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  {partialSegment.start.toFixed(1)}s
                </span>
              </div>
              <p style={{ fontSize: '1.05rem', color: 'var(--text-secondary)', paddingLeft: '4px', fontStyle: 'italic' }}>
                {partialSegment.text}...
              </p>
            </div>
          )}

          <div ref={transcriptEndRef} />
        </div>
      </div>

      {/* 우측: GPU 모니터링 및 녹음 컨트롤 보드 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
        {/* 마이크 시각화 보드 */}
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <h3 style={{ fontSize: '1rem', alignSelf: 'flex-start', marginBottom: '16px' }}>오디오 입력 주파수</h3>
          <div style={{
            width: '100%',
            height: '100px',
            backgroundColor: 'rgba(0,0,0,0.2)',
            borderRadius: 'var(--radius-sm)',
            overflow: 'hidden',
            border: '1px solid var(--border-light)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            position: 'relative'
          }}>
            <canvas ref={canvasRef} width="250" height="100" style={{ width: '100%', height: '100%' }} />
            {!isRecording && (
              <span style={{ position: 'absolute', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                마이크 비활성 상태
              </span>
            )}
          </div>
        </div>

        {/* GPU VRAM 실시간 현황 */}
        <div className="glass-panel" style={{ padding: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
            <HardDrive size={18} className="gradient-text" />
            <h3 style={{ fontSize: '1.1rem' }}>GPU 리소스 모니터</h3>
          </div>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '4px' }}>
                <span style={{ color: 'var(--text-secondary)' }}>VRAM 사용량</span>
                <strong>{gpuUsage > 0 ? `${gpuUsage} MB` : '대기중'}</strong>
              </div>
              <div style={{ width: '100%', height: '6px', backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: '3px', overflow: 'hidden' }}>
                <div style={{
                  width: `${gpuUsage > 0 ? Math.min((gpuUsage / 12000) * 100, 100) : 0}%`,
                  height: '100%',
                  background: 'var(--gradient-neon)',
                  transition: 'width 0.5s ease'
                }}></div>
              </div>
            </div>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              <span>GPU 모델</span>
              <span>RTX 3060 12GB</span>
            </div>
          </div>
        </div>

        {/* Diarization 결과 이동 알림 팝업 */}
        {completedSessionId && (
          <div className="glass-panel" style={{
            padding: '20px',
            background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.15) 0%, rgba(168, 85, 247, 0.15) 100%)',
            borderColor: 'var(--color-primary)',
            boxShadow: '0 0 25px rgba(99, 102, 241, 0.25)',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Clock size={18} color="#c084fc" />
              <h4 style={{ fontSize: '0.95rem', color: 'white' }}>화자 분리 처리 완료!</h4>
            </div>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              전체 대화에 대한 pyannote 화자 분리 매핑이 완료되었습니다. 결과물을 확인하고 수정해 보세요.
            </p>
            <Link href={`/sessions/${completedSessionId}`} className="btn btn-primary" style={{
              padding: '8px 16px',
              fontSize: '0.85rem',
              borderRadius: '9999px',
              textDecoration: 'none',
              marginTop: '4px'
            }}>
              상세 회의록 보기
              <ChevronRight size={14} />
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
