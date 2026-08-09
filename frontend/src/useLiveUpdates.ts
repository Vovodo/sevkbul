import { useEffect, useRef, useCallback } from 'react';

const API_BASE = (import.meta.env.VITE_API_URL || '').trim().replace(/\/+$/, '').replace(/\/api(\/v\d+)?$/i, '');

function getWsUrl(): string {
  if (API_BASE) {
    // Render / Production: https://xxx.onrender.com → wss://xxx.onrender.com/ws
    return API_BASE.replace(/^http/, 'ws') + '/ws';
  }
  // Local development: ws://localhost:8001/ws (aynı origin)
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws`;
}

export type WsEventType = 'scan' | 'undo' | 'reset' | 'find' | 'target_add' | 'target_clear' | 'target_import' | 'stock_import';

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
export function useLiveUpdates(onMessage: WsMessageHandler) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;

  const connect = useCallback(() => {
    // Halihazırda bağlıysa tekrar bağlanma
    if (wsRef.current && (wsRef.current.readyState === WebSocket.CONNECTING || wsRef.current.readyState === WebSocket.OPEN)) {
      return;
    }

    const url = getWsUrl();
    const ws = new WebSocket(url);

    ws.onopen = () => {
      // Bağlantı kuruldu — reconnect zamanlayıcısını temizle
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
      wsRef.current = null;
      // 3 saniye sonra yeniden bağlan
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
        wsRef.current.onclose = null; // Unmount'ta yeniden bağlanmayı engelle
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);
}
