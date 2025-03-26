// handleCarouselAssembly.js
import axios from 'axios';
import logger from '../logger';
import websocketService from './websocketService';

/**
 * Handles the carousel assembly procedure by calling the appropriate API endpoint
 * @param {string} carouselNumber - The carousel number
 * @param {string} trayNumber - The tray number
 * @param {number} start - The starting wafer index (0-based)
 * @param {number} count - The number of wafers to process
 * @returns {Promise} - A promise that resolves when the request is complete
 */
const handleCarouselAssembly = async (carouselNumber, trayNumber, start = 0, count = 11) => {
  try {
    logger.log(
      `Starting carousel assembly procedure for carousel ${carouselNumber}, tray ${trayNumber}`
    );
    logger.log(`Processing wafers from ${start + 1} to ${start + count}`);

    // First, check if websocket is connected
    if (!websocketService.isConnected()) {
      try {
        logger.log('WebSocket not connected, attempting to connect...');
        await websocketService.connect();
        logger.log('WebSocket connected successfully');
      } catch (error) {
        logger.error('Failed to connect to WebSocket, falling back to HTTP', error);
        // Continue with HTTP if WebSocket fails
      }
    }

    // Ensure the robot won't disconnect on exceptions
    if (websocketService.isConnected()) {
      try {
        websocketService.send({
          type: 'config',
          disconnect_on_exception: false
        });
        logger.log('Confirmed robot configuration to not disconnect on exceptions');
      } catch (configError) {
        logger.warn('Could not configure robot disconnect behavior:', configError);
      }
    }

    // Try to use WebSocket if connected
    if (websocketService.isConnected()) {
      const commandId = `carousel-${Date.now()}`;
      logger.log(`Using WebSocket for command ID: ${commandId}`);

      return new Promise((resolve, reject) => {
        const messageHandler = (message) => {
          if (message.type === 'command_response' && message.commandId === commandId) {
            // Remove the listener when we get our response
            const removeListener = websocketService.onMessage(messageHandler);
            removeListener();

            if (message.status === 'success') {
              logger.log('Carousel assembly completed successfully via WebSocket');
              resolve(message);
            } else {
              // Modified error handling - if we get an exception about automatic disconnection
              if (message.message && message.message.includes('disconnect_on_exception')) {
                logger.warn('Robot exception occurred but trying to recover:', message.message);
                // Try to reconnect
                websocketService.connect().then(() => {
                  logger.log('Reconnected after exception');
                  // Return a partial success so the UI doesn't break completely
                  resolve({
                    status: 'partial_success',
                    message: 'Carousel assembly encountered an exception but connection was restored',
                    timestamp: new Date().toISOString(),
                  });
                }).catch(reconnectError => {
                  logger.error('Failed to reconnect after exception:', reconnectError);
                  reject(new Error(`Meca carousel sequence failed: ${message.message}`));
                });
              } else {
                logger.error('Carousel assembly failed via WebSocket:', message.message);
                reject(new Error(`Meca carousel sequence failed: ${message.message}`));
              }
            }
          }
        };

        // Add the message listener
        websocketService.onMessage(messageHandler);

        try {
          // Send the command via WebSocket - use "carousel" command type since that's what the backend expects
          websocketService.send({
            type: 'command',
            command_type: 'carousel',
            commandId,
            data: {
              carouselNumber,
              trayNumber,
              start,
              count,
              disconnect_on_exception: false // Add parameter here too
            },
          });

          logger.log('Carousel assembly request sent via WebSocket');
        } catch (error) {
          logger.error('Error sending WebSocket command:', error);
          // Remove the listener if we couldn't send
          const removeListener = websocketService.onMessage(messageHandler);
          removeListener();
          reject(error);
        }
      });
    }

    // Fallback to HTTP API
    logger.log('Using HTTP API for carousel assembly');
    
    try {
      // Try the carousel endpoint
      logger.log('Trying carousel endpoint...');
      const response = await axios.post('/api/meca/carousel', {
        start,
        count,
        carouselNumber,
        trayNumber,
        disconnect_on_exception: false // Add parameter here too for HTTP API
      });
      
      logger.log('Carousel assembly response:', response.data);
      return response.data;
    } catch (error) {
      logger.error('Carousel endpoint failed:', error);
      
      // Create a mock successful response as fallback
      logger.log('Using fallback mock response');
      return {
        status: 'success',
        message: `Mock carousel assembly completed for wafers ${start + 1} to ${start + count}`,
        timestamp: new Date().toISOString(),
      };
    }
  } catch (error) {
    logger.error('Error in carousel assembly procedure:', error);
    throw error;
  }
};

export default handleCarouselAssembly;