// websocketService.js
import logger from '../logger';

class WebSocketService {
  constructor() {
    this.socket = null;
    this.isConnecting = false;
    this.messageListeners = new Set();
    this.statusListeners = new Set();
    this.disconnectListeners = new Set();
    this.reconnectTimeout = null;
    this.WEBSOCKET_URL = 'ws://localhost:8000/ws';
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
    const wasConnected = this.isConnected();
    this.socket = null;

    if (wasConnected) {
      this.disconnectListeners.forEach((listener) => listener());
    }
  }

  disconnect() {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

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
      throw new Error('Cannot send message - WebSocket is not connected');
    }

    try {
      this.socket.send(JSON.stringify(message));
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
