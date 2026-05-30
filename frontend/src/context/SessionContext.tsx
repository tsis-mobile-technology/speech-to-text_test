'use client';

import React, { createContext, useContext, useState, useCallback, useRef, useEffect, ReactNode } from 'react';

export interface Segment {
  id: string;
  start: number;
  end: number;
  text: string;
  speaker: string;
  confidence: number;
  is_final: boolean;
  corrected?: boolean;
  original_text?: string | null;
}

interface SessionContextType {
  // WebSocket 상태
  isConnected: boolean;
  wsError: string | null;

  // 세그먼트 상태
  segments: Segment[];
  partialSegment: Segment | null;
  gpuUsage: number;
  completedSessionId: string | null;

  // WebSocket 제어
  connect: (url: string) => void;
  disconnect: () => void;
  sendAudioChunk: (chunk: ArrayBuffer | Float32Array) => void;

  // 상태 업데이트
  addSegment: (segment: Segment) => void;
  setPartialSegment: (segment: Segment | null) => void;
  setGpuUsage: (usage: number) => void;
  setCompletedSessionId: (id: string | null) => void;
  clearSession: () => void;

  // 녹음 상태 및 오디오 제어
  isRecording: boolean;
  setIsRecording: (recording: boolean) => void;
  audioError: string | null;
  mediaStream: MediaStream | null;
  audioContext: AudioContext | null;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<void>;
}

const SessionContext = createContext<SessionContextType | undefined>(undefined);

export function SessionProvider({ children }: { children: ReactNode }) {
  // WebSocket 상태
  const [isConnected, setIsConnected] = useState(false);
  const [wsError, setWsError] = useState<string | null>(null);

  // 세그먼트 상태 (전역 유지)
  const [segments, setSegments] = useState<Segment[]>([]);
  const [partialSegment, setPartialSegment] = useState<Segment | null>(null);
  const [gpuUsage, setGpuUsage] = useState(0);
  const [completedSessionId, setCompletedSessionId] = useState<string | null>(null);

  // 녹음 및 오디오 상태
  const [isRecording, setIsRecording] = useState(false);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null);
  const [audioContext, setAudioContext] = useState<AudioContext | null>(null);

  // WebSocket refs
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectCountRef = useRef(0);
  // 회의 단위 안정적 세션 ID (재연결에도 유지 → 한 회의 = 한 세션)
  const meetingIdRef = useRef<string | null>(null);

  // 오디오 하드웨어 관련 refs
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);

  // WebSocket 연결
  const connect = useCallback((url: string) => {
    // 이미 연결되어 있거나 연결 중이면 재사용 (중복 연결 방지)
    if (wsRef.current && (
      wsRef.current.readyState === WebSocket.OPEN || 
      wsRef.current.readyState === WebSocket.CONNECTING
    )) {
      console.log('✅ WebSocket already connecting or connected');
      return;
    }

    // 새 연결 시도 시 재연결 카운트 리셋 (수동 종료 상태 해제)
    reconnectCountRef.current = 0;

    try {
      // 회의 단위 세션 ID 부여(없으면 생성). 재연결 시 동일 ID로 백엔드가 이어쓰기.
      if (!meetingIdRef.current) {
        meetingIdRef.current =
          (typeof crypto !== 'undefined' && crypto.randomUUID)
            ? crypto.randomUUID()
            : `m-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      }
      const sep = url.includes('?') ? '&' : '?';
      const fullUrl = `${url}${sep}session_id=${meetingIdRef.current}`;
      console.log('🔌 WebSocket 연결 중:', fullUrl);
      const ws = new WebSocket(fullUrl);

      ws.onopen = () => {
        console.log('✅ WebSocket connected');
        setIsConnected(true);
        setWsError(null);
        reconnectCountRef.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('📨 WebSocket message:', data.type);

          if (data.type === 'partial' && data.segment) {
            setPartialSegment(data.segment);
            if (data.gpu_usage_mb) setGpuUsage(data.gpu_usage_mb);
          } else if (data.type === 'final' && data.segment) {
            setSegments((prev) => {
              if (prev.some((s) => s.id === data.segment.id)) {
                return prev;
              }
              return [...prev, data.segment];
            });
            setPartialSegment(null);
            if (data.gpu_usage_mb) setGpuUsage(data.gpu_usage_mb);
          } else if (data.type === 'corrected' && data.segment_id) {
            // LLM 문맥 보정 결과로 해당 세그먼트 텍스트 교체
            setSegments((prev) =>
              prev.map((s) =>
                s.id === data.segment_id
                  ? { ...s, text: data.text, corrected: true, original_text: s.text }
                  : s
              )
            );
          } else if (data.type === 'speaker_updated') {
            if (data.segments && Array.isArray(data.segments)) {
              setSegments(data.segments);
            }
            if (data.session_id) {
              setCompletedSessionId(data.session_id);
            }
          } else if (data.type === 'error') {
            setWsError(data.error);
          }
        } catch (err) {
          console.error('❌ Failed to parse WebSocket message:', err);
        }
      };

      ws.onerror = (event) => {
        console.error('❌ WebSocket error:', event);
        setWsError('WebSocket connection error');
        setIsConnected(false);
      };

      ws.onclose = () => {
        console.log('❌ WebSocket closed');
        setIsConnected(false);
        wsRef.current = null;

        // 자동 재연결 (최대 5회)
        if (reconnectCountRef.current < 5) {
          reconnectCountRef.current += 1;
          const delay = Math.min(1000 * Math.pow(2, reconnectCountRef.current), 10000);
          console.log(`🔄 자동 재연결 ${reconnectCountRef.current}회, ${delay}ms 후...`);

          reconnectTimeoutRef.current = setTimeout(() => {
            connect(url);
          }, delay);
        } else {
          // 자동 재연결 실패 시 최종적으로 녹음 상태도 false로 변경
          setIsRecording(false);
        }
      };

      wsRef.current = ws;
    } catch (err) {
      console.error('❌ WebSocket 연결 실패:', err);
      setWsError(String(err));
      setIsConnected(false);
    }
  }, []);

  // 오디오 청크 전송
  const sendAudioChunk = useCallback((chunk: ArrayBuffer | Float32Array) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.send(chunk);
      } catch (err) {
        console.error('❌ Failed to send audio chunk:', err);
      }
    }
  }, []);

  // 마이크 캡처 시작
  const startRecording = useCallback(async () => {
    setAudioError(null);
    try {
      // 1. 마이크 미디어 스트림 획득 (단계적 폴백)
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
          video: false,
        });
      } catch (firstErr) {
        console.warn('Failed to getUserMedia with strict constraints, retrying with simple audio...', firstErr);
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            audio: true,
            video: false,
          });
        } catch (secondErr: any) {
          console.error('All getUserMedia attempts failed:', secondErr);
          if (secondErr.name === 'NotFoundError' || secondErr.message?.includes('device not found')) {
            throw new Error('연결된 마이크 장치를 찾을 수 없습니다. 마이크가 연결되어 있는지 또는 브라우저/OS 설정에서 마이크가 활성화되어 있는지 확인해주세요.');
          } else if (secondErr.name === 'NotAllowedError' || secondErr.name === 'PermissionDeniedError') {
            throw new Error('마이크 권한이 거부되었습니다. 브라우저 주소창의 권한 설정을 확인해주세요.');
          } else {
            throw secondErr;
          }
        }
      }
      
      mediaStreamRef.current = stream;
      setMediaStream(stream);

      // 2. 16kHz 가중 오디오 컨텍스트 생성 (Whisper 호환)
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate: 16000,
      });
      audioContextRef.current = audioCtx;
      setAudioContext(audioCtx);

      // 3. AudioWorklet 등록
      console.log('📦 AudioWorklet 로드 중: /audio-processor.worklet.js');
      try {
        await audioCtx.audioWorklet.addModule('/audio-processor.worklet.js');
        console.log('✅ AudioWorklet 로드 성공');
      } catch (workletErr: any) {
        console.error('❌ AudioWorklet 로드 실패:', workletErr);
        throw new Error(`AudioWorklet 로드 실패: ${workletErr.message}`);
      }

      const source = audioCtx.createMediaStreamSource(stream);
      console.log('✅ MediaStreamAudioSourceNode 생성 성공');

      const workletNode = new AudioWorkletNode(audioCtx, 'audio-stream-processor');
      console.log('✅ AudioWorkletNode 생성 성공');
      
      let chunkCount = 0;
      workletNode.port.onmessage = (event) => {
        const audioChunk = event.data as Float32Array;
        chunkCount++;
        if (chunkCount % 10 === 0) {
          console.log(`🎵 AudioWorklet에서 청크 수신 (총 ${chunkCount}개): ${audioChunk.length} 샘플`);
        }
        sendAudioChunk(audioChunk);
      };

      source.connect(workletNode);
      workletNode.connect(audioCtx.destination);

      sourceNodeRef.current = source;
      workletNodeRef.current = workletNode;
      
      setIsRecording(true);
      if (audioCtx.state === 'suspended') {
        await audioCtx.resume();
      }
      
    } catch (err: any) {
      console.error('Failed to access microphone or configure worklet:', err);
      setAudioError(err.message || '마이크 접근에 실패하였습니다.');
      setIsRecording(false);
    }
  }, [sendAudioChunk]);

  // 마이크 캡처 정지
  const stopRecording = useCallback(async () => {
    setIsRecording(false);
    
    // 노드 연결 해제 및 스트림 중지
    if (workletNodeRef.current) {
      try { workletNodeRef.current.disconnect(); } catch (e) {}
      workletNodeRef.current = null;
    }
    if (sourceNodeRef.current) {
      try { sourceNodeRef.current.disconnect(); } catch (e) {}
      sourceNodeRef.current = null;
    }
    if (mediaStreamRef.current) {
      try { mediaStreamRef.current.getTracks().forEach((track) => track.stop()); } catch (e) {}
      mediaStreamRef.current = null;
      setMediaStream(null);
    }
    if (audioContextRef.current) {
      try {
        if (audioContextRef.current.state !== 'closed') {
          await audioContextRef.current.close();
        }
      } catch (e) {}
      audioContextRef.current = null;
      setAudioContext(null);
    }
  }, []);

  // WebSocket 연결 해제
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      console.log('🔌 WebSocket 연결 해제 (명시적 회의 종료)');
      wsRef.current.onclose = null; // 자동 재연결 차단을 위해 온클로즈 핸들러 해제
      try {
        // 명시적 종료 신호 → 백엔드가 최종 후처리(화자분리/완료저장) 수행
        if (wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ command: 'stop' }));
        }
      } catch (e) {
        console.warn('stop 명령 전송 실패:', e);
      }
      wsRef.current.close();
      wsRef.current = null;
    }

    setIsConnected(false);
    setIsRecording(false);
  }, []);

  // 세션 초기화 (다음 '회의 시작'은 새 회의 → meetingId도 초기화하여 새 세션 발급)
  const clearSession = useCallback(() => {
    setSegments([]);
    setPartialSegment(null);
    setCompletedSessionId(null);
    setGpuUsage(0);
    setWsError(null);
    setAudioError(null);
    meetingIdRef.current = null;
  }, []);

  // Provider 전체가 언마운트될 때 리소스 해제
  useEffect(() => {
    return () => {
      console.log('🧹 SessionProvider 언마운트: 전체 리소스 정리');
      disconnect();
      // stopRecording도 동기적으로 실행
      if (workletNodeRef.current) {
        try { workletNodeRef.current.disconnect(); } catch (e) {}
      }
      if (sourceNodeRef.current) {
        try { sourceNodeRef.current.disconnect(); } catch (e) {}
      }
      if (mediaStreamRef.current) {
        try { mediaStreamRef.current.getTracks().forEach((track) => track.stop()); } catch (e) {}
      }
      if (audioContextRef.current) {
        try {
          if (audioContextRef.current.state !== 'closed') {
            audioContextRef.current.close();
          }
        } catch (e) {}
      }
    };
  }, [disconnect]);

  const value: SessionContextType = {
    isConnected,
    wsError,
    segments,
    partialSegment,
    gpuUsage,
    completedSessionId,
    connect,
    disconnect,
    sendAudioChunk,
    addSegment: (segment) => {
      setSegments((prev) => {
        if (prev.some((s) => s.id === segment.id)) return prev;
        return [...prev, segment];
      });
    },
    setPartialSegment,
    setGpuUsage,
    setCompletedSessionId,
    clearSession,
    isRecording,
    setIsRecording,
    audioError,
    mediaStream,
    audioContext,
    startRecording,
    stopRecording,
  };

  return (
    <SessionContext.Provider value={value}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const context = useContext(SessionContext);
  if (context === undefined) {
    throw new Error('useSession must be used within SessionProvider');
  }
  return context;
}
