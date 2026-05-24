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
    // 상태 확인
    const currentState = wsRef.current?.readyState;

    // 이미 연결 중이면 새 연결 시도하지 않음
    if (currentState === WebSocket.CONNECTING) {
      console.warn('⚠️ WebSocket이 이미 연결 중입니다. 중복 연결 방지.');
      console.warn(`📊 Current state: CONNECTING (${currentState})`);
      return;
    }

    // 이미 연결되어 있으면 먼저 종료
    if (currentState === WebSocket.OPEN) {
      console.warn('⚠️ 기존 WebSocket 연결이 있습니다. 종료 후 새로 연결합니다.');
      console.warn(`📊 Current state: OPEN (${currentState})`);
      try {
        wsRef.current?.close();
      } catch (err) {
        console.error('Error closing existing connection:', err);
      }
      // 이전 연결이 완전히 닫힐 때까지 대기
      return;
    }

    // CLOSING 또는 CLOSED 상태면 안전하게 새 연결 시도
    if (currentState === WebSocket.CLOSING || currentState === WebSocket.CLOSED || currentState === undefined) {
      console.log(`📊 Safe to create new connection. Current state: ${currentState ?? 'undefined'}`);
    }

    isManuallyClosed.current = false;
    setError(null);

    try {
      console.log(`🔌 WebSocket 연결 시도: ${url}`);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('✅ WebSocket connection established.');
        console.log(`📊 WebSocket state: ${ws.readyState} (OPEN)`);
        console.log(`📊 URL: ${ws.url}`);
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
        console.error('❌ WebSocket error:', err);
        const errorMsg = err instanceof Event
          ? '서버 연결 중 에러가 발생했습니다. 브라우저 콘솔을 확인하세요.'
          : String(err);
        setError(errorMsg);
      };

      ws.onclose = () => {
        console.log('❌ WebSocket connection closed.');
        console.warn(`📊 Reconnection attempt: ${reconnectAttemptsRef.current} / ${maxReconnectAttempts}`);
        setIsConnected(false);

        // 수동 종료가 아닐 경우 지수 백오프로 재연결 시도
        if (!isManuallyClosed.current && reconnectAttemptsRef.current < maxReconnectAttempts) {
          const delay = Math.pow(2, reconnectAttemptsRef.current) * 1000;
          console.log(`⏳ Attempting to reconnect in ${delay}ms... (attempt ${reconnectAttemptsRef.current + 1}/${maxReconnectAttempts})`);
          setTimeout(() => {
            reconnectAttemptsRef.current++;
            console.log(`🔄 Reconnecting now... (attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts})`);
            connect();
          }, delay);
        } else if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
          setError('서버 연결 시도 횟수를 초과했습니다. 새로고침을 해주세요.');
          console.error('❌ Max reconnection attempts exceeded');
        }

        // 만약 재연결을 시도하지 않는 경우에만 마이크 종료 (사용자의 의도적인 종료)
        if (isManuallyClosed.current || reconnectAttemptsRef.current >= maxReconnectAttempts) {
          if (onClose) onClose();
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
