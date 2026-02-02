import React, { useState, useCallback, useEffect, useRef } from 'react';
import Button from '../common/Button';
import { API_URL } from '../../utils/services/config';

/**
 * RecoveryPanel - Shows recovery options when a robot is in error/e-stop state
 *
 * This component displays when either the Meca or OT2 robot is in an error
 * state after an emergency stop. It provides:
 * - Information about which robot triggered the e-stop
 * - Quick Recovery option to resume workflow from where it stopped
 * - Safe Homing with stop/resume controls
 *
 * Auto-closes when robot transitions from error state to busy/idle (recovery succeeded).
 *
 * @param {string} robotType - 'meca' or 'ot2'
 * @param {string} status - Current status of the robot
 * @param {object} stepInfo - Optional current step information
 * @param {function} onRecoveryComplete - Callback when recovery completes
 * @param {function} onClose - Callback to close the panel (called on auto-close)
 */
const RecoveryPanel = ({ robotType, status, stepInfo, onRecoveryComplete, onClose }) => {
  const [loading, setLoading] = useState(false);
  const [actionInProgress, setActionInProgress] = useState(null);
  const [recoveryStatus, setRecoveryStatus] = useState(null);
  const [error, setError] = useState(null);
  const [safeHomingStatus, setSafeHomingStatus] = useState({ active: false, stopped: false });
  const [recoveryMessage, setRecoveryMessage] = useState(null);

  // Track previous status to detect successful recovery transitions
  const prevStatusRef = useRef(status);

  const API_BASE = `${API_URL}/api`;

  // Determine if this panel should be shown
  // Check for both 'emergency_stop' (backend enum value) and 'emergency_stopped' (legacy)
  const isErrorState = status === 'error' || status === 'disconnected' || status === 'emergency_stop' || status === 'emergency_stopped';

  // Auto-close panel when robot transitions from error -> working state
  useEffect(() => {
    const prevStatus = prevStatusRef.current;
    const wasInError = prevStatus === 'error' || prevStatus === 'emergency_stop' || prevStatus === 'emergency_stopped' || prevStatus === 'disconnected';
    const nowWorking = status === 'busy' || status === 'idle' || status === 'connected';

    if (wasInError && nowWorking) {
      // Recovery succeeded - close panel after brief delay for feedback
      const timeout = setTimeout(() => {
        onClose?.();
        onRecoveryComplete?.();
      }, 500);
      return () => clearTimeout(timeout);
    }
  }, [status, onClose, onRecoveryComplete]);

  // Update previous status ref after each render
  useEffect(() => {
    prevStatusRef.current = status;
  }, [status]);

  // API call helper
  const apiCall = useCallback(async (endpoint, method = 'POST', body = null) => {
    const options = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body) {
      options.body = JSON.stringify(body);
    }
    const response = await fetch(`${API_BASE}${endpoint}`, options);
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Request failed: ${response.status}`);
    }
    return response.json();
  }, []);

  // Poll safe homing status when active (Meca only)
  useEffect(() => {
    if (robotType !== 'meca' || !safeHomingStatus.active) return;

    const interval = setInterval(async () => {
      try {
        const result = await apiCall('/meca/recovery/safe-homing-status', 'GET');
        setSafeHomingStatus(result.data || { active: false, stopped: false });
      } catch (err) {
        console.warn('Failed to poll safe homing status:', err);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [robotType, safeHomingStatus.active, apiCall]);

  // Quick Recovery handler - resume workflow from where it stopped
  const handleQuickRecovery = useCallback(async () => {
    setLoading(true);
    setActionInProgress('quick');
    setError(null);
    setRecoveryMessage(null);
    try {
      const endpoint = robotType === 'meca'
        ? '/meca/recovery/quick-recovery'
        : '/ot2/recovery/quick-recovery';
      const result = await apiCall(endpoint, 'POST');

      if (result.data?.message) {
        setRecoveryStatus({ ...result.data, success: true });
        // Show resuming feedback - panel will auto-close when WebSocket state arrives
        setRecoveryMessage('Resuming sequence...');
        // Note: onRecoveryComplete is now called by the auto-close effect when status changes
      } else if (result.data?.error) {
        setError(result.data.error);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setActionInProgress(null);
    }
  }, [apiCall, robotType]);

  // Safe Homing handlers (Meca)
  const handleStartSafeHoming = useCallback(async () => {
    setLoading(true);
    setActionInProgress('safe-homing');
    setError(null);
    try {
      const result = await apiCall('/meca/recovery/start-safe-homing', 'POST', { speed_percent: 20 });
      if (result.data?.status === 'completed') {
        setSafeHomingStatus({ active: false, stopped: false });
        onRecoveryComplete?.();
      } else {
        setSafeHomingStatus({ active: true, stopped: false });
      }
      setRecoveryStatus(result.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setActionInProgress(null);
    }
  }, [apiCall, onRecoveryComplete]);

  const handleStopSafeHoming = useCallback(async () => {
    setLoading(true);
    setActionInProgress('stop-homing');
    setError(null);
    try {
      const result = await apiCall('/meca/recovery/stop-safe-homing', 'POST');
      setSafeHomingStatus(prev => ({ ...prev, stopped: true }));
      setRecoveryStatus(result.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setActionInProgress(null);
    }
  }, [apiCall]);

  const handleResumeSafeHoming = useCallback(async () => {
    setLoading(true);
    setActionInProgress('resume-homing');
    setError(null);
    try {
      const result = await apiCall('/meca/recovery/resume-safe-homing', 'POST');
      if (result.data?.status === 'completed') {
        setSafeHomingStatus({ active: false, stopped: false });
        onRecoveryComplete?.();
      } else {
        setSafeHomingStatus(prev => ({ ...prev, stopped: false }));
      }
      setRecoveryStatus(result.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setActionInProgress(null);
    }
  }, [apiCall, onRecoveryComplete]);

  // OT2 Safe Home Reverse Path
  const handleOT2SafeHome = useCallback(async () => {
    setLoading(true);
    setActionInProgress('ot2-safe-home');
    setError(null);
    try {
      const result = await apiCall('/ot2/recovery/safe-home-reverse', 'POST');
      setRecoveryStatus(result.data);
      if (result.data?.homed) {
        onRecoveryComplete?.();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setActionInProgress(null);
    }
  }, [apiCall, onRecoveryComplete]);

  if (!isErrorState) {
    return null;
  }

  const isMeca = robotType === 'meca';

  return (
    <div className="bg-red-50 border border-red-200 rounded-lg p-4 mt-4">
      {/* Header - Shows which robot is in E-Stop */}
      <div className="flex items-center mb-4">
        <svg
          className="h-6 w-6 text-red-500 mr-2"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
          />
        </svg>
        <h3 className="text-lg font-semibold text-red-800">
          Emergency Stop Active for: {isMeca ? 'Meca' : 'OT2'}
        </h3>
      </div>

      {/* Error message */}
      {error && (
        <div className="mb-4 p-3 bg-red-100 border border-red-300 rounded text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Main Recovery Options */}
      <div className="space-y-4">
        {/* Option 1: Quick Recovery */}
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div className="flex-1">
              <h4 className="font-semibold text-gray-800 flex items-center">
                <span className="bg-blue-100 text-blue-800 text-xs px-2 py-0.5 rounded mr-2">
                  Option 1
                </span>
                Quick Recovery
              </h4>
              <p className="text-sm text-gray-600 mt-1">
                Continue workflow from where it stopped
              </p>
              {stepInfo && (
                <p className="text-sm text-blue-600 mt-1">
                  Resume from Step {stepInfo.index} of {stepInfo.total}: {stepInfo.name}
                </p>
              )}
            </div>
            <Button
              variant="primary"
              size="sm"
              onClick={handleQuickRecovery}
              loading={actionInProgress === 'quick'}
              disabled={loading}
            >
              {stepInfo ? `Resume Step ${stepInfo.index}` : 'Quick Recovery'}
            </Button>
          </div>
        </div>

        {/* Option 2: Safe Homing */}
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div className="flex-1">
              <h4 className="font-semibold text-gray-800 flex items-center">
                <span className="bg-orange-100 text-orange-800 text-xs px-2 py-0.5 rounded mr-2">
                  Option 2
                </span>
                Safe Homing
              </h4>
              <p className="text-sm text-gray-600 mt-1">
                Return to home position at 20% speed (stoppable)
              </p>
              {safeHomingStatus.active && (
                <p className="text-sm text-orange-600 mt-1">
                  {safeHomingStatus.stopped ? 'Paused - Robot holding position' : 'In progress...'}
                </p>
              )}
            </div>
            <div className="flex gap-2">
              {isMeca ? (
                // Meca Safe Homing with Stop/Resume
                safeHomingStatus.active ? (
                  safeHomingStatus.stopped ? (
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={handleResumeSafeHoming}
                      loading={actionInProgress === 'resume-homing'}
                      disabled={loading}
                    >
                      Resume
                    </Button>
                  ) : (
                    <Button
                      variant="warning"
                      size="sm"
                      onClick={handleStopSafeHoming}
                      loading={actionInProgress === 'stop-homing'}
                      disabled={loading}
                    >
                      Stop
                    </Button>
                  )
                ) : (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handleStartSafeHoming}
                    loading={actionInProgress === 'safe-homing'}
                    disabled={loading}
                  >
                    Start Safe Homing
                  </Button>
                )
              ) : (
                // OT2 Safe Home (reverse path)
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleOT2SafeHome}
                  loading={actionInProgress === 'ot2-safe-home'}
                  disabled={loading}
                >
                  Safe Home (Reverse Path)
                </Button>
              )}
            </div>
          </div>
        </div>

      </div>

      {/* Recovery message (e.g., "Resuming sequence...") */}
      {recoveryMessage && (
        <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded text-sm flex items-center">
          <svg className="animate-spin h-4 w-4 mr-2 text-blue-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <p className="text-blue-700 font-medium">{recoveryMessage}</p>
        </div>
      )}

      {/* Status info */}
      {recoveryStatus && recoveryStatus.message && !recoveryMessage && (
        <div className="mt-4 p-3 bg-gray-50 border border-gray-200 rounded text-sm">
          <p className="text-gray-700">{recoveryStatus.message}</p>
        </div>
      )}
    </div>
  );
};

export default RecoveryPanel;
