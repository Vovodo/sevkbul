import { useEffect, useRef, useCallback, useState } from 'react';
import { API_BASE } from './api';

export function getWsUrl(): string {
  if (API_BASE) {
    // https://xxx.rfqcollector.com → wss://xxx.rfqcollector.com/ws
    return API_BASE.replace(/^http/, 'ws') + '/ws';
  }
  // API_BASE boşken (VITE_API_URL girilmemişse) production backend'e doğrudan bağlan
  // window.location.host mobile servisine işaret edebilir, backend'e değil!
  // Bu yüzden hardcoded production backend URL kullanılır.
  return 'wss://sevkbulapi.rfqcollector.com/ws';
}

export type WsEventType = 'scan' | 'undo' | 'reset' | 'find' | 'target_add' | 'target_clear' | 'target_import' | 'stock_import';

export interface WsMessage {
  event: WsEventType;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any;
}

type WsMessageHandler = (msg: WsMessage) => void;

/**
 * Gerçek zamanlı mobil WebSocket hook'u.
 * Otomatik yeniden bağlanma ve canlı durum (connected / disconnected) takibi.
 */
export function useLiveUpdates(onMessage?: WsMessageHandler) {
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;

  const connect = useCallback(() => {
    if (wsRef.current && (wsRef.current.readyState === WebSocket.CONNECTING || wsRef.current.readyState === WebSocket.OPEN)) {
      return;
    }

    try {
      const url = getWsUrl();
      const ws = new WebSocket(url);

      ws.onopen = () => {
        setIsConnected(true);
        if (reconnectTimer.current) {
          clearTimeout(reconnectTimer.current);
          reconnectTimer.current = null;
        }
      };

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data) as WsMessage;
          if (handlerRef.current) {
            handlerRef.current(msg);
          }
        } catch {
          // ignore malformed frame
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;
        // 3 saniye sonra otomatik yeniden bağlan
        reconnectTimer.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        setIsConnected(false);
        try {
          ws.close();
        } catch {
          // ignore
        }
      };

      wsRef.current = ws;
    } catch {
      setIsConnected(false);
      reconnectTimer.current = setTimeout(connect, 3000);
    }
  }, []);

  useEffect(() => {
    connect();

    // 25s ping interval (keep-alive)
    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        try {
          wsRef.current.send('ping');
        } catch {
          // ignore
        }
      }
    }, 25000);

    return () => {
      clearInterval(pingInterval);
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
      if (wsRef.current) {
        wsRef.current.onclose = null;
        try {
          wsRef.current.close();
        } catch {
          // ignore
        }
        wsRef.current = null;
      }
    };
  }, [connect]);

  return { isConnected };
}
