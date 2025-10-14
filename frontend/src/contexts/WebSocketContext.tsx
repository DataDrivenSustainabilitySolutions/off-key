import React, { createContext, useContext, useEffect, useRef, useState, ReactNode } from 'react';
import { INTERVALS } from '@/lib/constants';

export type WebSocketMessage = {
  type: 'anomaly_detected' | 'telemetry_update' | 'charger_status';
  data: any;
  timestamp: string;
};

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

export interface WebSocketContextType {
  connectionStatus: ConnectionStatus;
  lastMessage: WebSocketMessage | null;
  sendMessage: (message: any) => void;
  connect: () => void;
  disconnect: () => void;
  subscribe: (type: string, callback: (data: any) => void) => () => void;
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined);

export const WebSocketProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('disconnected');
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const subscribersRef = useRef<Map<string, ((data: any) => void)[]>>(new Map());
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = 5;

  const getWebSocketUrl = (): string => {
    const isDevelopment = import.meta.env.DEV;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    
    if (isDevelopment) {
      return `${protocol}//localhost:8000/ws`;
    }
    
    const wsUrl = import.meta.env.VITE_WS_URL;
    if (wsUrl) return wsUrl;
    
    return `${protocol}//${window.location.host}/ws`;
  };

  const connect = React.useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      setConnectionStatus('connecting');
      const ws = new WebSocket(getWebSocketUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        setConnectionStatus('connected');
        reconnectAttempts.current = 0;
        console.log('WebSocket connected');
      };

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          setLastMessage(message);
          
          // Notify subscribers
          const subscribers = subscribersRef.current.get(message.type) || [];
          subscribers.forEach(callback => callback(message.data));
        } catch (error) {
          console.error('Error parsing WebSocket message:', error);
        }
      };

      ws.onclose = (event) => {
        setConnectionStatus('disconnected');
        console.log('WebSocket disconnected:', event.code, event.reason);
        
        // Attempt reconnection if not intentional
        if (event.code !== 1000 && reconnectAttempts.current < maxReconnectAttempts) {
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
          reconnectAttempts.current++;
          
          console.log(`Attempting to reconnect in ${delay}ms (attempt ${reconnectAttempts.current})`);
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        }
      };

      ws.onerror = (error) => {
        setConnectionStatus('error');
        console.error('WebSocket error:', error);
      };
    } catch (error) {
      setConnectionStatus('error');
      console.error('Failed to create WebSocket connection:', error);
    }
  }, []);

  const disconnect = React.useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    
    if (wsRef.current) {
      wsRef.current.close(1000, 'Intentional disconnect');
      wsRef.current = null;
    }
    
    setConnectionStatus('disconnected');
  }, []);

  const sendMessage = React.useCallback((message: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    } else {
      console.warn('WebSocket is not connected. Message not sent:', message);
    }
  }, []);

  const subscribe = React.useCallback((type: string, callback: (data: any) => void) => {
    const subscribers = subscribersRef.current.get(type) || [];
    subscribers.push(callback);
    subscribersRef.current.set(type, subscribers);

    // Return unsubscribe function
    return () => {
      const currentSubscribers = subscribersRef.current.get(type) || [];
      const updatedSubscribers = currentSubscribers.filter(cb => cb !== callback);
      if (updatedSubscribers.length === 0) {
        subscribersRef.current.delete(type);
      } else {
        subscribersRef.current.set(type, updatedSubscribers);
      }
    };
  }, []);

  // Auto-connect on mount
  useEffect(() => {
    connect();
    
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  // Heartbeat to maintain connection
  useEffect(() => {
    if (connectionStatus === 'connected') {
      const heartbeatInterval = setInterval(() => {
        sendMessage({ type: 'ping', timestamp: new Date().toISOString() });
      }, INTERVALS.WEBSOCKET_HEARTBEAT);

      return () => clearInterval(heartbeatInterval);
    }
  }, [connectionStatus, sendMessage]);

  return (
    <WebSocketContext.Provider
      value={{
        connectionStatus,
        lastMessage,
        sendMessage,
        connect,
        disconnect,
        subscribe,
      }}
    >
      {children}
    </WebSocketContext.Provider>
  );
};

export const useWebSocket = (): WebSocketContextType => {
  const context = useContext(WebSocketContext);
  if (!context) {
    throw new Error('useWebSocket must be used within a WebSocketProvider');
  }
  return context;
};

// Hook for anomaly notifications specifically
export const useAnomalyNotifications = () => {
  const { subscribe } = useWebSocket();
  const [anomalies, setAnomalies] = useState<any[]>([]);

  useEffect(() => {
    const unsubscribe = subscribe('anomaly_detected', (data) => {
      setAnomalies(prev => [data, ...prev].slice(0, 50)); // Keep last 50 anomalies
    });

    return unsubscribe;
  }, [subscribe]);

  return { anomalies };
};