import { useEffect, useRef, useCallback, useState } from 'react';
import { getApiBase, getActiveSessionId } from './api';

export function getWsUrl(sessionId?: number): string {
  const sid = sessionId ?? getActiveSessionId();
  const base = getApiBase();
  if (base) {
    // Render / Production: https://xxx.rfqcollector.com → wss://xxx.rfqcollector.com/ws
    return `${base.replace(/^http/, 'ws')}/ws?session_id=${sid}`;
  }
  if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}/ws?session_id=${sid}`;
  }
  return `wss://sevkbulapi.rfqcollector.com/ws?session_id=${sid}`;
}

export type WsEventType =
  | 'scan'
  | 'undo'
  | 'reset'
  | 'scans_reset'
  | 'group_scans_reset'
  | 'find'
  | 'target_add'
  | 'target_clear'
  | 'target_import'
  | 'stock_import'
  | 'group_delete'
  | 'recalculate'
  | 'recalculate_progress'
  | 'excel_headers_updated'
  | 'sessions_updated';

export interface WsMessage {
  event: WsEventType;
  session_id?: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any;
}

type WsMessageHandler = (msg: WsMessage) => void;

/**
 * Oturum (session_id) odasına duyarlı gerçek zamanlı WebSocket hook'u.
 */
export function useLiveUpdates(onMessage: WsMessageHandler, sessionId?: number): boolean {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handlerRef = useRef(onMessage);
  const sessionIdRef = useRef<number>(sessionId ?? getActiveSessionId());
  const [connected, setConnected] = useState(false);
  handlerRef.current = onMessage;
  sessionIdRef.current = sessionId ?? getActiveSessionId();

  const connect = useCallback(() => {
    if (wsRef.current && (wsRef.current.readyState === WebSocket.CONNECTING || wsRef.current.readyState === WebSocket.OPEN)) {
      return;
    }

    const url = getWsUrl(sessionIdRef.current);
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
      ws.close();
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN && sessionId != null) {
      wsRef.current.send(JSON.stringify({ action: 'switch_session', session_id: sessionId }));
    }
  }, [sessionId]);

  useEffect(() => {
    connect();

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
