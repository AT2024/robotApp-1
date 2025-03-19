// services/configService.js
import websocketService from './websocketService';

class ConfigService {
  constructor() {
    this.configListeners = new Set();
  }

  // Connect to the backend
  async connect(onConfigUpdate) {
    if (onConfigUpdate) {
      this.configListeners.add(onConfigUpdate);
    }

    // Use the websocket service for connection
    websocketService.connect();

    // Listen for config-related messages
    websocketService.onMessage((message) => {
      if (message.type === 'config_data' || message.type === 'config_update') {
        this.configListeners.forEach(listener => listener(message));
      }
    });
  }

  // Request configuration data
  async requestConfig(configType) {
    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        reject(new Error('Config request timed out'));
      }, 15000);

      const messageHandler = (message) => {
        if (
          (message.type === 'config_data' || message.type === 'get_config') &&
          message.data?.config_type === configType
        ) {
          clearTimeout(timeoutId);
          websocketService.onMessage(messageHandler); // Remove listener
          resolve(message);
        }
      };

      websocketService.onMessage(messageHandler);
      
      // Send the config request
      websocketService.send({
        type: 'get_config',
        config_type: configType,
      });
    });
  }

  // Save configuration changes
  async saveConfig(config) {
    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        reject(new Error('Save operation timed out'));
      }, 10000);

      const messageHandler = (message) => {
        if (message.type === 'save_config_response') {
          clearTimeout(timeoutId);
          websocketService.onMessage(messageHandler); // Remove listener
          
          if (message.success) {
            resolve(message);
          } else {
            reject(new Error(message.message || 'Failed to save configuration'));
          }
        }
      };

      websocketService.onMessage(messageHandler);
      
      // Send the save request
      websocketService.send({
        type: 'save_config',
        config_type: config.config_type,
        data: config.data,
      });
    });
  }

  // Clean up
  disconnect() {
    this.configListeners.clear();
    // Note: We don't disconnect the websocket service here since other services might be using it
  }
}

const configService = new ConfigService();
export default configService;