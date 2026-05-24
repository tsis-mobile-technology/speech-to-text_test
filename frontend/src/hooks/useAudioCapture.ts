import { useState, useRef, useCallback } from 'react';

interface UseAudioCaptureProps {
  onAudioChunk: (chunk: Float32Array) => void;
}

export function useAudioCapture({ onAudioChunk }: UseAudioCaptureProps) {
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);

  const startRecording = useCallback(async () => {
    setError(null);
    try {
      // 1. 마이크 미디어 스트림 획득 (엄격한 제약 조건 실패 시 단계적 폴백)
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

      // 2. 16kHz 가중 오디오 컨텍스트 생성 (Whisper 호환)
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate: 16000,
      });
      audioContextRef.current = audioCtx;

      // 3. AudioWorklet 등록
      await audioCtx.audioWorklet.addModule('/audio-processor.worklet.js');
      
      const source = audioCtx.createMediaStreamSource(stream);
      const workletNode = new AudioWorkletNode(audioCtx, 'audio-stream-processor');
      
      // Worklet으로부터 청크 데이터를 받았을 때 실행할 이벤트 바인딩
      workletNode.port.onmessage = (event) => {
        const audioChunk = event.data as Float32Array;
        onAudioChunk(audioChunk);
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
      setError(err.message || '마이크 접근에 실패하였습니다.');
      setIsRecording(false);
    }
  }, [onAudioChunk]);

  const stopRecording = useCallback(async () => {
    setIsRecording(false);
    
    // 노드 연결 해제 및 스트림 중지
    if (workletNodeRef.current) {
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }
    if (sourceNodeRef.current) {
      sourceNodeRef.current.disconnect();
      sourceNodeRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    if (audioContextRef.current) {
      if (audioContextRef.current.state !== 'closed') {
        await audioContextRef.current.close();
      }
      audioContextRef.current = null;
    }
  }, []);

  return {
    isRecording,
    error,
    startRecording,
    stopRecording,
    audioContext: audioContextRef.current,
    mediaStream: mediaStreamRef.current,
  };
}
