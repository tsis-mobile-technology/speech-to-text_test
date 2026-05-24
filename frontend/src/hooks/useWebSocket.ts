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
    isManuallyClosed.current = false;
    setError(null);
    
    try {
      console.log(`Connecting to WebSocket: ${url}`);
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
          onMessage(data);
        } catch (err) {
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
      wsRef.current.send(chunk);
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
