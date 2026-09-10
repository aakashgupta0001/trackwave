// Centralized WebSocket client for TrackWave real-time streaming updates.
// Handles auto-reconnect, topic subscriptions, message deserialization, and connection lifecycle.

import { useEffect, useRef, useState } from 'react'

const WS_BASE_URL: string =
  (import.meta.env.VITE_WS_BASE_URL as string | undefined) ?? 'ws://localhost:8000'

export type WebSocketMessageType =
  | 'TRAIN_STATE_UPDATE'
  | 'ETA_UPDATE'
  | 'NETWORK_IMPACT_UPDATE'
  | 'ALERT_CREATED'
  | 'ALERT_UPDATED'
  | 'train_state'
  | 'prediction_update'
  | 'network_alert'
  | 'congestion_risk'
  | 'heartbeat'

export type WebSocketMessage<T = any> = {
  type?: WebSocketMessageType
  event_type?: WebSocketMessageType
  topic: string
  train_number?: string
  station_code?: string
  timestamp: string
  data: T
}

export type ConnectionState = 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED' | 'ERROR'

export class TrackWaveWebSocketClient {
  private socket: WebSocket | null = null
  private url: string
  private reconnectAttempts = 0
  private maxReconnectAttempts = 10
  private reconnectTimer: any = null
  private listeners: Set<(msg: WebSocketMessage) => void> = new Set()
  private stateListeners: Set<(state: ConnectionState) => void> = new Set()
  private isExplicitClose = false

  constructor(path: string) {
    const normPath = path.startsWith('/') ? path : `/${path}`
    this.url = `${WS_BASE_URL}${normPath}`
  }

  public connect(): void {
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return
    }

    this.isExplicitClose = false
    this.notifyState('CONNECTING')

    try {
      this.socket = new WebSocket(this.url)

      this.socket.onopen = () => {
        this.reconnectAttempts = 0
        this.notifyState('CONNECTED')
      }

      this.socket.onmessage = (event) => {
        try {
          if (event.data === 'pong') return
          const payload = JSON.parse(event.data) as WebSocketMessage
          this.listeners.forEach((listener) => listener(payload))
        } catch (err) {
          console.warn('[TrackWaveWS] Message parse error:', err)
        }
      }

      this.socket.onclose = () => {
        this.notifyState('DISCONNECTED')
        if (!this.isExplicitClose) {
          this.scheduleReconnect()
        }
      }

      this.socket.onerror = () => {
        this.notifyState('ERROR')
      }
    } catch {
      this.notifyState('ERROR')
      this.scheduleReconnect()
    }
  }

  public disconnect(): void {
    this.isExplicitClose = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.socket) {
      this.socket.close()
      this.socket = null
    }
    this.notifyState('DISCONNECTED')
  }

  public subscribe(callback: (msg: WebSocketMessage) => void): () => void {
    this.listeners.add(callback)
    return () => {
      this.listeners.delete(callback)
    }
  }

  public onStateChange(callback: (state: ConnectionState) => void): () => void {
    this.stateListeners.add(callback)
    return () => {
      this.stateListeners.delete(callback)
    }
  }

  private notifyState(state: ConnectionState): void {
    this.stateListeners.forEach((listener) => listener(state))
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.warn('[TrackWaveWS] Max reconnect attempts reached for:', this.url)
      return
    }
    const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), 15000)
    this.reconnectAttempts++
    this.reconnectTimer = setTimeout(() => {
      this.connect()
    }, delay)
  }
}

export function useWebSocketFeed<T = any>(
  path: string | null,
  onMessage?: (msg: WebSocketMessage<T>) => void
) {
  const [connectionState, setConnectionState] = useState<ConnectionState>('DISCONNECTED')
  const [lastMessage, setLastMessage] = useState<WebSocketMessage<T> | null>(null)
  const clientRef = useRef<TrackWaveWebSocketClient | null>(null)
  const callbackRef = useRef(onMessage)

  useEffect(() => {
    callbackRef.current = onMessage
  }, [onMessage])

  useEffect(() => {
    if (!path) return

    const client = new TrackWaveWebSocketClient(path)
    clientRef.current = client

    const unsubState = client.onStateChange(setConnectionState)
    const unsubMsg = client.subscribe((msg: WebSocketMessage<T>) => {
      setLastMessage(msg)
      if (callbackRef.current) {
        callbackRef.current(msg)
      }
    })

    client.connect()

    return () => {
      unsubState()
      unsubMsg()
      client.disconnect()
      clientRef.current = null
    }
  }, [path])

  return { connectionState, lastMessage }
}