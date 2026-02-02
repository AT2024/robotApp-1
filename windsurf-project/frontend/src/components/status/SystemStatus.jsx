// SystemStatus.jsx
import React, { useEffect, useState, useCallback, useRef } from 'react';
import websocketService from '../../utils/services/websocketService';
import logger from '../../utils/logger';
import RecoveryPanel from '../recovery/RecoveryPanel';
import ConfirmationModal from '../common/ConfirmationModal';
import { API_URL } from '../../utils/services/config';

const SystemStatus = ({ onStatusChange }) => {
  const [statuses, setStatuses] = useState({
    backend: 'disconnected',
    meca: 'disconnected',
    arduino: 'disconnected',
    ot2: 'disconnected',
  });

  // Meca connection management state
  const [mecaConnecting, setMecaConnecting] = useState(false);
  const [mecaDisconnecting, setMecaDisconnecting] = useState(false);
  const [showPortalConfirmModal, setShowPortalConfirmModal] = useState(false);
  const [connectionError, setConnectionError] = useState(null);

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

  // State to force-hide recovery panels after successful recovery
  // (panel will auto-re-show if status is still in error)
  const [mecaRecoveryDismissed, setMecaRecoveryDismissed] = useState(false);
  const [ot2RecoveryDismissed, setOt2RecoveryDismissed] = useState(false);

  // Check if any robot needs recovery (include emergency_stop state from backend enum)
  const mecaNeedsRecovery = (statuses.meca === 'error' || statuses.meca === 'disconnected' || statuses.meca === 'emergency_stop' || statuses.meca === 'emergency_stopped') && !mecaRecoveryDismissed;
  const ot2NeedsRecovery = (statuses.ot2 === 'error' || statuses.ot2 === 'disconnected' || statuses.ot2 === 'emergency_stop' || statuses.ot2 === 'emergency_stopped') && !ot2RecoveryDismissed;

  // Reset dismissed state when robot status changes to working state
  useEffect(() => {
    if (statuses.meca === 'connected' || statuses.meca === 'busy' || statuses.meca === 'idle') {
      setMecaRecoveryDismissed(false);
    }
  }, [statuses.meca]);

  useEffect(() => {
    if (statuses.ot2 === 'connected' || statuses.ot2 === 'busy' || statuses.ot2 === 'idle') {
      setOt2RecoveryDismissed(false);
    }
  }, [statuses.ot2]);

  // Handler for when recovery completes
  const handleRecoveryComplete = useCallback(() => {
    // Request fresh status after recovery
    if (websocketService.isConnected()) {
      websocketService.send({
        type: 'get_status',
        timestamp: new Date().toISOString(),
      });
    }
  }, []);

  // Handlers for closing recovery panels (auto-close after successful recovery)
  const handleMecaRecoveryClose = useCallback(() => {
    setMecaRecoveryDismissed(true);
    handleRecoveryComplete();
  }, [handleRecoveryComplete]);

  const handleOt2RecoveryClose = useCallback(() => {
    setOt2RecoveryDismissed(true);
    handleRecoveryComplete();
  }, [handleRecoveryComplete]);

  // API helper function
  const apiCall = async (endpoint, method = 'POST') => {
    const response = await fetch(`${API_URL}/api${endpoint}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Request failed: ${response.status}`);
    }
    return response.json();
  };

  // Handle Meca disconnect
  const handleMecaDisconnect = async () => {
    setConnectionError(null);
    setMecaDisconnecting(true);
    try {
      await apiCall('/meca/disconnect-safe');
      console.log('Meca disconnected successfully');
    } catch (error) {
      console.error('Failed to disconnect Meca:', error);
      setConnectionError(error.message || 'Failed to disconnect');
    } finally {
      setMecaDisconnecting(false);
    }
  };

  // Handle Meca connect (two-step: TCP connect then activate)
  const handleMecaConnect = async () => {
    setConnectionError(null);
    setMecaConnecting(true);
    setShowPortalConfirmModal(false);
    try {
      // Step 1: TCP connect
      await apiCall('/meca/connect-safe');
      console.log('Meca TCP connected');

      // Step 2: Activate and home
      await apiCall('/meca/confirm-activation');
      console.log('Meca activated and homed');
    } catch (error) {
      console.error('Failed to connect Meca:', error);
      setConnectionError(error.message || 'Failed to connect');
    } finally {
      setMecaConnecting(false);
    }
  };

  // Handle Connect button click - show confirmation modal
  const handleConnectButtonClick = () => {
    setConnectionError(null);
    setShowPortalConfirmModal(true);
  };

  // Modal handlers
  const handlePortalConfirmYes = () => {
    handleMecaConnect();
  };

  const handlePortalConfirmNo = () => {
    setShowPortalConfirmModal(false);
  };

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

              {/* Meca Disconnect/Connect button */}
              {device === 'meca' && (
                <div className='mt-auto'>
                  {status === 'connected' && (
                    <button
                      onClick={handleMecaDisconnect}
                      disabled={mecaDisconnecting}
                      className='w-full px-3 py-1.5 text-sm font-medium text-white bg-white/20 hover:bg-white/30 border border-white/40 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2'
                    >
                      {mecaDisconnecting ? (
                        <>
                          <svg className='animate-spin h-4 w-4' viewBox='0 0 24 24'>
                            <circle className='opacity-25' cx='12' cy='12' r='10' stroke='currentColor' strokeWidth='4' fill='none' />
                            <path className='opacity-75' fill='currentColor' d='M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z' />
                          </svg>
                          Disconnecting...
                        </>
                      ) : (
                        'Disconnect'
                      )}
                    </button>
                  )}
                  {status === 'disconnected' && (
                    <button
                      onClick={handleConnectButtonClick}
                      disabled={mecaConnecting}
                      className='w-full px-3 py-1.5 text-sm font-medium text-white bg-white/20 hover:bg-white/30 border border-white/40 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2'
                    >
                      {mecaConnecting ? (
                        <>
                          <svg className='animate-spin h-4 w-4' viewBox='0 0 24 24'>
                            <circle className='opacity-25' cx='12' cy='12' r='10' stroke='currentColor' strokeWidth='4' fill='none' />
                            <path className='opacity-75' fill='currentColor' d='M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z' />
                          </svg>
                          Connecting...
                        </>
                      ) : (
                        'Connect'
                      )}
                    </button>
                  )}
                  {connectionError && (
                    <p className='mt-1 text-xs text-white/90 bg-white/10 rounded px-2 py-1'>
                      {connectionError}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Recovery Panels - Show when robots are in error state */}
      {mecaNeedsRecovery && (
        <RecoveryPanel
          robotType="meca"
          status={statuses.meca}
          onRecoveryComplete={handleRecoveryComplete}
          onClose={handleMecaRecoveryClose}
        />
      )}
      {ot2NeedsRecovery && (
        <RecoveryPanel
          robotType="ot2"
          status={statuses.ot2}
          onRecoveryComplete={handleRecoveryComplete}
          onClose={handleOt2RecoveryClose}
        />
      )}

      {/* Meca Portal Confirmation Modal */}
      <ConfirmationModal
        isOpen={showPortalConfirmModal}
        onClose={handlePortalConfirmNo}
        onConfirm={handlePortalConfirmYes}
        title="Confirm Meca Portal Disconnected"
        message="Did you disconnect the robot from Meca Portal? The Mecademic robot can only be connected to one application at a time."
        confirmText="Yes, Connect"
        cancelText="No, Cancel"
        variant="primary"
        loading={mecaConnecting}
      />
    </div>
  );
};

export default React.memo(SystemStatus);
