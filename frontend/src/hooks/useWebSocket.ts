import { useEffect, useRef, useState, useCallback } from 'react';

interface UseWebSocketProps {
  url: string;
  onMessage: (data: any) => void;
  onOpen?: () => void;
  onClose?: () => void;
}

export function useWebSocket({ url, onMessage, onOpen, onClose }: UseWebSocketProps) {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const maxReconnectAttempts = 5;
  const isManuallyClosed = useRef(false);

  const connect = useCallback(() => {
    // 이미 연결 중이면 새 연결 시도하지 않음
    if (wsRef.current && wsRef.current.readyState === WebSocket.CONNECTING) {
      console.warn('⚠️ WebSocket이 이미 연결 중입니다. 중복 연결 방지.');
      return;
    }

    // 이미 연결되어 있으면 먼저 종료
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      console.warn('⚠️ 기존 WebSocket 연결이 있습니다. 종료 후 새로 연결합니다.');
      wsRef.current.close();
    }

    isManuallyClosed.current = false;
    setError(null);

    try {
      console.log(`🔌 WebSocket 연결 시도: ${url}`);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('WebSocket connection established.');
        setIsConnected(true);
        reconnectAttemptsRef.current = 0;
        if (onOpen) onOpen();
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log(`📨 WebSocket 메시지 수신:`, data.type);
          onMessage(data);
        } catch (err) {
          console.warn(`⚠️ JSON 파싱 실패:`, err);
          // 바이너리 데이터 수신은 무시 (서버는 JSON만 전송하므로)
        }
      };

      ws.onerror = (err) => {
        console.error('WebSocket encountered an error:', err);
        setError('서버 연결 중 에러가 발생했습니다.');
      };

      ws.onclose = () => {
        console.log('WebSocket connection closed.');
        setIsConnected(false);
        if (onClose) onClose();

        // 수동 종료가 아닐 경우 지수 백오프로 재연결 시도
        if (!isManuallyClosed.current && reconnectAttemptsRef.current < maxReconnectAttempts) {
          const delay = Math.pow(2, reconnectAttemptsRef.current) * 1000;
          console.log(`Attempting to reconnect in ${delay}ms...`);
          setTimeout(() => {
            reconnectAttemptsRef.current++;
            connect();
          }, delay);
        } else if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
          setError('서버 연결 시도 횟수를 초과했습니다. 새로고침을 해주세요.');
        }
      };
      
    } catch (err: any) {
      console.error('Failed to create WebSocket:', err);
      setError(err.message || 'WebSocket 생성에 실패했습니다.');
    }
  }, [url, onMessage, onOpen, onClose]);

  const disconnect = useCallback(() => {
    isManuallyClosed.current = true;
    if (wsRef.current) {
      // 닫기 전에 클라이언트에 stop 텍스트 커맨드 전송하여 최종 화자분리 트리거
      if (wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ command: 'stop' }));
      }
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const sendAudioChunk = useCallback((chunk: Float32Array) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      // Float32Array를 직접 전송하여 버퍼 오프셋 및 슬라이스 오작동 방지
      try {
        console.log(`🔊 오디오 청크 전송: ${chunk.length} 샘플`);
        wsRef.current.send(chunk);
      } catch (err) {
        console.error('❌ 오디오 청크 전송 실패:', err);
      }
    } else {
      console.warn(`⚠️ WebSocket 미준비 (상태: ${wsRef.current?.readyState})`);
    }
  }, []);

  // 컴포넌트 언마운트 시 자동 해제
  useEffect(() => {
    return () => {
      isManuallyClosed.current = true;
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  return {
    isConnected,
    error,
    connect,
    disconnect,
    sendAudioChunk,
    ws: wsRef.current,
  };
}
