// config.js
// Get API base URL from environment variables with fallback
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080';

// Export API_URL for HTTP requests
export const API_URL = API_BASE_URL;

// Convert HTTP URL to WebSocket URL
export const WS_URL = API_BASE_URL.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws';

export const MAX_RETRIES = 3;
export const RETRY_DELAY = 1000;
export const CONNECTION_TIMEOUT = 5000;