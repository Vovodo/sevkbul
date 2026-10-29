import { useEffect, useRef, useCallback, useState } from 'react';
import { getApiBase } from './api';

export function getWsUrl(): string {
  const base = getApiBase();
  if (base) {
    // Render / Production: https://xxx.rfqcollector.com → wss://xxx.rfqcollector.com/ws
    return base.replace(/^http/, 'ws') + '/ws';
  }
  if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}/ws`;
  }
  return 'wss://sevkbulapi.rfqcollector.com/ws';
}

export type WsEventType = 'scan' | 'undo' | 'reset' | 'find' | 'target_add' | 'target_clear' | 'target_import' | 'stock_import' | 'group_delete' | 'recalculate' | 'recalculate_progress';

export interface WsMessage {
  event: WsEventType;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any;
}

type WsMessageHandler = (msg: WsMessage) => void;

/**
 * Gerçek zamanlı güncelleme WebSocket hook'u.
 * Otomatik yeniden bağlanma desteği ile.
 */
export function useLiveUpdates(onMessage: WsMessageHandler): boolean {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handlerRef = useRef(onMessage);
  const [connected, setConnected] = useState(false);
  handlerRef.current = onMessage;

  const connect = useCallback(() => {
    // Halihazırda bağlıysa tekrar bağlanma
    if (wsRef.current && (wsRef.current.readyState === WebSocket.CONNECTING || wsRef.current.readyState === WebSocket.OPEN)) {
      return;
    }

    const url = getWsUrl();
    const ws = new WebSocket(url);

    ws.onopen = () => {
      setConnected(true);
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
    };

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data) as WsMessage;
        handlerRef.current(msg);
      } catch {
        // Geçersiz mesaj — yoksay
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      reconnectTimer.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      // Hata durumunda bağlantıyı kapat (onclose yeniden bağlanmayı tetikleyecek)
      ws.close();
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    connect();

    // 25 saniyede bir ping gönder (bağlantıyı canlı tut — Render 60s idle timeout)
    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping');
      }
    }, 25000);

    return () => {
      clearInterval(pingInterval);
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return connected;
}
