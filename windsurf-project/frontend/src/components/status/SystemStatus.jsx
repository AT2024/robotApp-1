// SystemStatus.jsx
import React, { useEffect, useState, useCallback, useRef } from 'react';
import websocketService from '../../utils/services/websocketService';
import logger from '../../utils/logger';

const SystemStatus = ({ onStatusChange }) => {
  const [statuses, setStatuses] = useState({
    backend: 'disconnected',
    meca: 'disconnected',
    arduino: 'disconnected',
    ot2: 'disconnected',
  });

  // Handle status updates with improved logging
  const handleStatusUpdate = useCallback(
    (message) => {
      if (message.type === 'status_update' && message.data) {
        const { type, status } = message.data;

        if (type && typeof status === 'string') {
          const normalizedStatus = status.toLowerCase();

          console.log('Received status update:', {
            type,
            originalStatus: status,
            normalizedStatus,
            currentStatuses: statuses,
          });

          setStatuses((prevStatuses) => {
            const newStatuses = {
              ...prevStatuses,
              [type]: normalizedStatus,
            };

            // Log the status change
            console.log('Updating statuses:', {
              previous: prevStatuses,
              new: newStatuses,
              changed: prevStatuses[type] !== normalizedStatus,
            });

            return newStatuses;
          });
        }
      }
    },
    []
  );

  // Notify parent of status changes via useEffect to avoid render-time setState
  useEffect(() => {
    onStatusChange?.(statuses);
  }, [statuses, onStatusChange]);


  // Set up WebSocket connection
  useEffect(() => {
    const messageHandler = websocketService.onStatus(handleStatusUpdate);

    // Initial connection
    websocketService.connect().then(() => {
      console.log('WebSocket connected, requesting initial status');
      // Add small delay to ensure connection is fully established
      setTimeout(() => {
        if (websocketService.isConnected()) {
          websocketService.send({
            type: 'get_status',
            timestamp: new Date().toISOString(),
          });
        }
      }, 100);
    }).catch(error => {
      console.error('Failed to connect to WebSocket:', error);
    });

    return () => messageHandler();
  }, [handleStatusUpdate]);

  // Polling for status updates
  useEffect(() => {
    const pollInterval = setInterval(() => {
      if (websocketService.isConnected()) {
        try {
          websocketService.send({
            type: 'get_status',
            timestamp: new Date().toISOString(),
          });
        } catch (error) {
          console.error('Failed to send status request:', error);
        }
      } else {
        console.log('WebSocket not connected, skipping status request');
      }
    }, 10000);

    return () => clearInterval(pollInterval);
  }, []);

  return (
    <div className='bg-white rounded-xl shadow-xl p-6 mb-6'>
      <h2 className='text-xl font-semibold text-gray-900 mb-6'>System Status</h2>
      <div className='grid grid-cols-2 md:grid-cols-4 gap-4'>
        {Object.entries(statuses).map(([device, status]) => (
          <div
            key={device}
            className={`rounded-lg p-4 ${
              status === 'connected'
                ? 'bg-green-500'
                : status === 'connecting'
                ? 'bg-yellow-500'
                : 'bg-red-500'
            } shadow-lg transition-all duration-300`}>
            <div className='flex flex-col h-full'>
              <div className='flex justify-between items-start mb-3'>
                <div className='flex-1'>
                  <h3 className='text-xl font-semibold text-white capitalize'>{device}</h3>
                  <p className='text-white/90 capitalize'>{status}</p>
                </div>
                <div
                  className={`h-3 w-3 rounded-full bg-white/30 ${
                    status === 'connecting' ? 'animate-pulse' : ''
                  }`}></div>
              </div>
              
              
              {/* Info for backend */}
              {device === 'backend' && (
                <div className='mt-auto text-xs text-white/70'>
                  Core system
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default React.memo(SystemStatus);
