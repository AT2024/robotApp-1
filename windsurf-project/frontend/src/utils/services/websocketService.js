// websocketService.js
import logger from '../logger';
import { WS_URL } from './config';

class WebSocketService {
  constructor() {
    this.socket = null;
    this.isConnecting = false;
    this.messageListeners = new Set();
    this.statusListeners = new Set();
    this.disconnectListeners = new Set();
    this.reconnectTimeout = null;
    this.reconnectAttempts = 0;
    this.WEBSOCKET_URL = WS_URL;
    this.MAX_RECONNECT_DELAY = 5000;
  }

  isConnected() {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  async connect() {
    // Prevent multiple simultaneous connection attempts
    if (this.isConnecting || this.isConnected()) {
      logger.log('Already connected or connecting');
      return;
    }

    this.isConnecting = true;

    try {
      await this._createWebSocketConnection();
      
      // After successful connection, configure the robot not to disconnect on exceptions
      if (this.isConnected()) {
        this.send({
          type: 'config',
          disconnect_on_exception: false
        });
        logger.log('Configured robot to not disconnect on exceptions');
      }
    } catch (error) {
      logger.error('WebSocket connection failed:', error);
      throw error;
    } finally {
      this.isConnecting = false;
    }
  }

  _createWebSocketConnection() {
    return new Promise((resolve, reject) => {
      try {
        logger.log(`Attempting to connect to WebSocket at ${this.WEBSOCKET_URL}`);
        this.socket = new WebSocket(this.WEBSOCKET_URL);

        const timeoutId = setTimeout(() => {
          if (this.socket?.readyState !== WebSocket.OPEN) {
            this.socket?.close();
            reject(new Error('WebSocket connection timeout'));
          }
        }, 5000);

        this.socket.onopen = () => {
          clearTimeout(timeoutId);
          logger.log('WebSocket connected');
          resolve();
        };

        this.socket.onclose = (event) => {
          clearTimeout(timeoutId);
          logger.log('WebSocket connection closed');

          if (this.socket) {
            this._handleDisconnect();
          }
        };

        this.socket.onerror = (error) => {
          clearTimeout(timeoutId);
          logger.error('WebSocket error:', error);

          if (!this.isConnected()) {
            reject(error);
          }
        };

        this.socket.onmessage = (event) => {
          this._handleMessage(event);
        };
      } catch (error) {
        reject(error);
      }
    });
  }

  _handleMessage(event) {
    try {
      const message = JSON.parse(event.data);
      logger.log('Received WebSocket message:', message);

      if (message.type === 'status_update') {
        this.statusListeners.forEach((listener) => listener(message));
      }

      this.messageListeners.forEach((listener) => listener(message));
    } catch (error) {
      logger.error('Error processing WebSocket message:', error);
    }
  }

  _handleDisconnect() {
    // FIX: Always notify disconnect listeners when socket closes
    // Previously, this checked wasConnected AFTER setting socket to null, so it was always false
    this.socket = null;

    // Always notify disconnect listeners - UI needs to know about disconnection
    this.disconnectListeners.forEach((listener) => listener());

    // Always attempt to reconnect after a disconnect
    this._scheduleReconnect();
  }

  _scheduleReconnect() {
    // Clear existing timeout
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
    }

    // Schedule reconnection with exponential backoff
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts || 0), this.MAX_RECONNECT_DELAY);
    this.reconnectAttempts = (this.reconnectAttempts || 0) + 1;
    
    logger.log(`Scheduling reconnection attempt ${this.reconnectAttempts} in ${delay}ms`);
    
    this.reconnectTimeout = setTimeout(async () => {
      try {
        await this.connect();
        this.reconnectAttempts = 0; // Reset on successful connection
      } catch (error) {
        logger.error('Reconnection failed:', error);
        // Will schedule another attempt via _handleDisconnect
      }
    }, delay);
  }

  disconnect() {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    // Reset reconnection attempts
    this.reconnectAttempts = 0;

    if (this.socket) {
      const socket = this.socket;
      this.socket = null;

      try {
        socket.close();
      } catch (error) {
        logger.error('Error closing WebSocket:', error);
      }
    }
  }

  send(message) {
    if (!this.isConnected()) {
      const error = 'Cannot send message - WebSocket is not connected';
      logger.error(error);
      throw new Error(error);
    }

    try {
      const jsonMessage = JSON.stringify(message);
      this.socket.send(jsonMessage);
      logger.log('Sent WebSocket message:', message);
    } catch (error) {
      logger.error('Error sending WebSocket message:', error);
      throw error;
    }
  }

  onMessage(callback) {
    this.messageListeners.add(callback);
    return () => this.messageListeners.delete(callback);
  }

  onStatus(callback) {
    this.statusListeners.add(callback);
    return () => this.statusListeners.delete(callback);
  }

  onDisconnect(callback) {
    this.disconnectListeners.add(callback);
    return () => this.disconnectListeners.delete(callback);
  }

  clearListeners() {
    this.messageListeners.clear();
    this.statusListeners.clear();
    this.disconnectListeners.clear();
  }
}

// Create a singleton instance
const websocketService = new WebSocketService();

export default websocketService;