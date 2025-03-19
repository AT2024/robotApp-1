// services/ot2Service.js
import { BACKEND_URL } from './configService';

export const ot2Service = {
  runProtocol: async (data) => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/ot2/run-protocol`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to run OT2 protocol:', error);
      throw error;
    }
  },

  getStatus: async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/ot2/status`);

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to get OT2 status:', error);
      throw error;
    }
  },

  stopProtocol: async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/ot2/stop`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to stop OT2:', error);
      throw error;
    }
  },
};
