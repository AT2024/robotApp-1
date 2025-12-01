// spreading_page.jsx
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'react-toastify';
import websocketService from '../utils/services/websocketService';
import logger from '../utils/logger';
import { SystemStatus } from '../components/status';
import { ProgressSteps, StepContent } from '../components/steps';
import { EmergencyButton, SecondaryButton, PauseButton, ResumeButton, ResetButton } from '../components/buttons';
import { ConfirmationModal } from '../components/common';
import { BatchProgress, BatchErrorDialog, AllCompleteDialog } from '../components/batch';

const ROBOT_MAP = {
  MECA: 'meca',
  OT2: 'ot2',
  ARDUINO: 'arduino',
};

// localStorage key for batch state persistence
const BATCH_STORAGE_KEY = 'spreading_batch_state';

// Helper to load saved batch state from localStorage
const loadSavedBatchState = () => {
  try {
    const saved = localStorage.getItem(BATCH_STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      logger.log('Loaded saved batch state:', parsed);
      return parsed;
    }
  } catch (e) {
    logger.error('Failed to load saved batch state:', e);
  }
  return { currentBatch: 0, batchResults: [] };
};

const SpreadingPage = () => {
  const location = useLocation();
  const navigate = useNavigate();

  // Load saved batch state from localStorage first
  const savedBatchState = loadSavedBatchState();

  // Core state management with meaningful initial values
  // Always start at step 0 - don't restore from localStorage
  const [activeStep, setActiveStep] = useState(0);
  const [systemStatus, setSystemStatus] = useState({
    backend: 'disconnected',
    meca: 'disconnected',
    arduino: 'disconnected',
    ot2: 'disconnected',
  });
  const [trayInfo, setTrayInfo] = useState(null);
  const [emergencyStopActive, setEmergencyStopActive] = useState(false);
  const [emergencyStopStopping, setEmergencyStopStopping] = useState(false);
  const [stepConfirmations, setStepConfirmations] = useState({});
  const [ot2Status, setOt2Status] = useState('idle');
  const [connectionError, setConnectionError] = useState(false);
  const [lastError, setLastError] = useState(null);

  // Pause/Resume functionality state
  const [systemPaused, setSystemPaused] = useState(false);
  const [pausedOperations, setPausedOperations] = useState([]);
  const [pauseReason, setPauseReason] = useState('');

  // Step-specific pause functionality state
  const [stepPaused, setStepPaused] = useState(false);
  const [pausedStepName, setPausedStepName] = useState('');
  const [pausedStepIndex, setPausedStepIndex] = useState(-1);

  // Confirmation modal state
  const [confirmationModal, setConfirmationModal] = useState({
    isOpen: false,
    title: '',
    message: '',
    action: null,
    variant: 'primary'
  });

  // Batch workflow state - initialized from localStorage (savedBatchState loaded at top)
  const [currentBatch, setCurrentBatch] = useState(savedBatchState.currentBatch);
  const [batchResults, setBatchResults] = useState(savedBatchState.batchResults);
  const [totalWafers, setTotalWafers] = useState(55);
  const [totalBatches, setTotalBatches] = useState(11);
  const [failedWafers, setFailedWafers] = useState([]);
  const [showErrorDialog, setShowErrorDialog] = useState(false);
  const [showAllComplete, setShowAllComplete] = useState(false);
  const [currentWafer, setCurrentWafer] = useState(0);
  const [isProcessing, setIsProcessing] = useState(false);

  // WebSocket connection status
  const [wsConnected, setWsConnected] = useState(false);

  // Refs to hold current values for WebSocket callback (avoids stale closure)
  const currentBatchRef = useRef(currentBatch);
  const totalBatchesRef = useRef(totalBatches);

  // Define workflow steps with their associated robot commands
  const steps = [
    {
      label: 'Create Pick Up',
      robot: 'MECA',
      status: 'waiting',
      hasPress: true,
      onClick: async () => {
        try {
          const batchStart = currentBatch * 5;
          logger.log(`Initiating MECA pickup operation for batch ${currentBatch + 1} (wafers ${batchStart + 1}-${batchStart + 5})`);
          websocketService.send({
            type: 'command',
            command_type: 'meca_pickup',
            data: {
              start: batchStart,
              count: 5,
              is_last_batch: currentBatch === totalBatches - 1
            },
          });
        } catch (error) {
          logger.error('Pickup operation failed:', error);
          setLastError('Failed to initiate pickup operation');
        }
      },
      confirm: 'Confirm inert wafer tray is loaded secure in place',
    },
    {
      label: 'Vacuum Operation',
      confirm: 'Confirm Vacuum pump is on',
      robot: 'ARDUINO',
      status: 'waiting',
      hasPress: true,
      onClick: async () => {
        try {
          logger.log('Starting vacuum operation');
          websocketService.send({
            type: 'command',
            command_type: 'arduino_vacuum',
            data: {
              operation: 'start',
              parameters: { mode: 'initial' },
            },
          });
        } catch (error) {
          logger.error('Vacuum operation failed:', error);
          setLastError('Failed to start vacuum operation');
        }
      },
    },
    {
      label: 'OT2 Process',
      confirm: 'Confirm spreading tips are on up position and 5 wafers are in place',
      robot: 'OT2',
      status: 'waiting',
      hasPress: true,
      onClick: async () => {
        try {
          logger.log('Initiating OT2 protocol operation');
          websocketService.send({
            type: 'command',
            command_type: 'ot2_protocol',
            data: {
              protocol_name: 'liquid_handling',
              volume: 50,
              source_well: 'A1',
              dest_well: 'B1',
            },
          });
        } catch (error) {
          logger.error('OT2 protocol operation failed:', error);
          setLastError('Failed to initiate OT2 protocol');
        }
      },
    },
    {
      label: 'Use Fingers To Spread',
      confirm: 'Confirm spreading tips are on down position',
      robot: 'ARDUINO',
      status: 'waiting',
      hasPress: true,
      onClick: async () => {
        try {
          logger.log('Initiating finger spreading operation');
          websocketService.send({
            type: 'command',
            command_type: 'arduino_vacuum',
            data: {
              operation: 'spread_fingers',
              parameters: { position: 'down' },
            },
          });
        } catch (error) {
          logger.error('Finger spreading failed:', error);
          setLastError('Failed to initiate finger spreading');
        }
      },
    },
    {
      label: 'Spreading',
      robot: 'ARDUINO',
      status: 'waiting',
      hasPress: true,
      onClick: async () => {
        try {
          logger.log('Starting spreading operation');
          websocketService.send({
            type: 'command',
            command_type: 'arduino_vacuum',
            data: {
              operation: 'spread',
              parameters: { mode: 'normal' },
            },
          });
        } catch (error) {
          logger.error('Spreading operation failed:', error);
          setLastError('Failed to start spreading operation');
        }
      },
    },
    {
      label: 'Shut Down Fingers',
      robot: 'ARDUINO',
      status: 'waiting',
      hasPress: true,
      onClick: async () => {
        try {
          logger.log('Initiating fingers shutdown');
          websocketService.send({
            type: 'command',
            command_type: 'arduino_vacuum',
            data: {
              operation: 'fingers_shutdown',
            },
          });
        } catch (error) {
          logger.error('Finger shutdown failed:', error);
          setLastError('Failed to shut down fingers');
        }
      },
    },
    {
      label: 'Final Vacuum',
      robot: 'ARDUINO',
      status: 'waiting',
      hasPress: true,
      onClick: async () => {
        try {
          logger.log('Starting final vacuum operation');
          websocketService.send({
            type: 'command',
            command_type: 'arduino_vacuum',
            data: {
              operation: 'final',
            },
          });
        } catch (error) {
          logger.error('Final vacuum failed:', error);
          setLastError('Failed to start final vacuum');
        }
      },
    },
    {
      label: 'Move to Baking Tray',
      confirm: 'Confirm spreading tips are on up position',
      robot: 'MECA',
      status: 'waiting',
      hasPress: true,
      onClick: async () => {
        try {
          const batchStart = currentBatch * 5;
          logger.log(`Initiating move to baking tray for batch ${currentBatch + 1} (wafers ${batchStart + 1}-${batchStart + 5})`);
          websocketService.send({
            type: 'command',
            command_type: 'meca_drop',
            data: {
              start: batchStart,
              count: 5,
              is_last_batch: currentBatch === totalBatches - 1,
              current_step: activeStep,
              step_name: steps[activeStep].label
            },
          });
        } catch (error) {
          logger.error('Move to baking failed:', error);
          setLastError('Failed to move to baking tray');
        }
      },
    },
  ];

  // Handle system status updates
  const handleStatusChange = useCallback(
    (newStatuses) => {
      logger.log('Received new system statuses:', newStatuses);
      setSystemStatus(newStatuses);

      // Progress workflow when OT2 completes its operation
      if (newStatuses.ot2 === 'complete' && activeStep === 2) {
        logger.log('OT2 process completed, advancing to next step');
        setActiveStep((prev) => prev + 1);
      }

      // Update connection error state
      const isBackendDisconnected = newStatuses.backend === 'disconnected';
      logger.log(
        'Backend connection status:',
        isBackendDisconnected ? 'disconnected' : 'connected'
      );
      setConnectionError(isBackendDisconnected);
    },
    [activeStep]
  );

  // Initialize tray information
  useEffect(() => {
    if (location.state?.trayInfo) {
      logger.log('Setting tray information:', location.state.trayInfo);
      setTrayInfo(location.state.trayInfo);
    } else {
      logger.log('No tray information found, redirecting to form');
      navigate('/spreading/form');
    }
  }, [location.state, navigate]);

  // Save batch state to localStorage whenever it changes
  // Note: Don't save activeStep - always start at step 0 on page load
  useEffect(() => {
    const stateToSave = { currentBatch, batchResults };
    localStorage.setItem(BATCH_STORAGE_KEY, JSON.stringify(stateToSave));
    logger.log('Saved batch state to localStorage:', stateToSave);
  }, [currentBatch, batchResults]);

  // Keep refs in sync with state (prevents stale closure in WebSocket handler)
  useEffect(() => {
    currentBatchRef.current = currentBatch;
  }, [currentBatch]);

  useEffect(() => {
    totalBatchesRef.current = totalBatches;
  }, [totalBatches]);

  // Fetch sequence config on mount
  useEffect(() => {
    const fetchSequenceConfig = async () => {
      try {
        const response = await fetch('/api/meca/sequence-config');
        if (response.ok) {
          const result = await response.json();
          const config = result.data || result;
          setTotalWafers(config.total_wafers || 55);
          setTotalBatches(config.total_batches || Math.ceil((config.total_wafers || 55) / 5));
          logger.log('Fetched sequence config:', config);
        } else {
          logger.warn('Failed to fetch sequence config, using defaults');
        }
      } catch (error) {
        logger.error('Error fetching sequence config:', error);
        // Keep default values
      }
    };
    fetchSequenceConfig();
  }, []);

  // Set up WebSocket connection and message handling
  useEffect(() => {
    logger.log('Initializing WebSocket connection');
    websocketService.connect();

    // Track initial connection status
    setWsConnected(websocketService.isConnected());

    // Subscribe to disconnect events
    const disconnectUnsubscribe = websocketService.onDisconnect(() => {
      logger.warn('WebSocket disconnected!');
      setWsConnected(false);
      // Note: Removed toast notification - yellow banner provides visual feedback instead
    });

    // Check connection status periodically
    const connectionCheckInterval = setInterval(() => {
      const connected = websocketService.isConnected();
      setWsConnected(prevConnected => {
        if (connected && !prevConnected) {
          // Connection restored - just update state, yellow banner will hide automatically
          logger.log('WebSocket connection restored');
        }
        return connected;
      });
    }, 1000);

    const messageUnsubscribe = websocketService.onMessage((message) => {
      logger.log('Received WebSocket message:', message);

      if (message.type === 'command_response') {
        if (message.status === 'success') {
          if (message.command_type === 'ot2_protocol') {
            logger.log('OT2 protocol started successfully');
            setOt2Status('running');
          } else if (message.command_type === 'pause_system') {
            logger.log('System paused successfully');
            setSystemPaused(true);
            setPauseReason(message.data?.reason || 'System paused');
            setPausedOperations(message.paused_operations || []);
          } else if (message.command_type === 'resume_system') {
            logger.log('System resumed successfully');
            setSystemPaused(false);
            setPauseReason('');
            setPausedOperations([]);
          } else if (message.command_type === 'emergency_stop') {
            if (message.status === 'acknowledged') {
              logger.log('🚨 Emergency stop acknowledged by backend - validating robot states');
              // Keep showing stopping state until completion
            } else if (message.status === 'validating') {
              logger.log('🔍 Emergency stop validating robot connections:', message.data);
              const { operational_robots, unavailable_robots } = message.data || {};
              if (unavailable_robots && unavailable_robots.length > 0) {
                logger.warn(`⚠️  Warning: ${unavailable_robots.length} robots unavailable: ${unavailable_robots.join(', ')}`);
              }
              if (operational_robots && operational_robots.length > 0) {
                logger.log(`✅ Found ${operational_robots.length} operational robots: ${operational_robots.join(', ')}`);
              }
            } else if (message.status === 'success') {
              logger.log('✅ Emergency stop completed successfully');
              setEmergencyStopStopping(false);
              setEmergencyStopActive(true);

              // Show success details
              const data = message.data || {};
              if (data.total_stopped > 0) {
                setLastError(`Emergency stop successful: ${data.total_stopped} robot(s) stopped`);
                // Clear error after 5 seconds for success messages
                setTimeout(() => setLastError(''), 5000);
              }
            } else if (message.status === 'partial_success') {
              logger.warn('⚠️  Emergency stop partially successful');
              setEmergencyStopStopping(false);
              setEmergencyStopActive(true);

              // Show partial success details
              const data = message.data || {};
              const errorMsg = `Partial emergency stop: ${data.total_stopped || 0} stopped, ${(data.failed_stops || []).length} failed, ${(data.unavailable_robots || []).length} unavailable`;
              setLastError(errorMsg);
              logger.warn(errorMsg);
            } else if (message.status === 'error') {
              logger.error('❌ Emergency stop failed:', message.message);
              setEmergencyStopStopping(false);
              setEmergencyStopActive(false); // Reset to allow retry

              // Show detailed error information
              const data = message.data || {};
              let errorMsg = message.message || 'Emergency stop failed';

              if (data.error_type === 'no_operational_robots') {
                errorMsg = 'EMERGENCY STOP FAILED: No robots are connected or operational!';
                if (data.robot_statuses) {
                  const statusDetails = Object.entries(data.robot_statuses)
                    .map(([robot, status]) => `${robot}: ${status.backend_state}`)
                    .join(', ');
                  logger.error(`Robot states: ${statusDetails}`);
                }
              } else if (data.failed_stops && data.failed_stops.length > 0) {
                const failedRobots = data.failed_stops.map(f => `${f.robot_id}: ${f.error}`).join('; ');
                errorMsg += ` | Failed robots: ${failedRobots}`;
              }

              setLastError(errorMsg);
              setConnectionError(data.error_type === 'no_operational_robots');
            } else if (message.status === 'completed') {
              // Legacy status for backward compatibility
              logger.log('Emergency stop completed (legacy status)');
              setEmergencyStopStopping(false);
              setEmergencyStopActive(true);
            }
          }
        } else {
          logger.error('Command failed:', message.error);
          setLastError(message.error);
          if (message.error?.includes('timeout')) {
            setConnectionError(true);
          }
        }
      } else if (message.type === 'step_status_update') {
        // Handle step-specific status updates (like pause/resume broadcasts)
        if (message.data) {
          const { paused, pause_reason, step_index, step_name } = message.data;

          if (typeof paused === 'boolean') {
            setSystemPaused(paused);
            setStepPaused(paused);
            setPauseReason(pause_reason || '');

            if (paused) {
              setPausedStepName(step_name || '');
              setPausedStepIndex(step_index || -1);
              logger.log(`Step ${step_index} (${step_name}) paused: ${pause_reason}`);
            } else {
              setPausedStepName('');
              setPausedStepIndex(-1);
              logger.log(`Step ${step_index} (${step_name}) resumed`);
              setPausedOperations([]);
            }
          }
        }
      } else if (message.type === 'system_status_update') {
        // Handle system-wide status updates for backward compatibility
        if (message.data) {
          const { system_paused, pause_reason, current_step } = message.data;

          if (typeof system_paused === 'boolean') {
            setSystemPaused(system_paused);
            setPauseReason(pause_reason || '');

            if (system_paused) {
              logger.log(`System paused: ${pause_reason}`);
            } else {
              logger.log('System resumed');
              setPausedOperations([]);
            }
          }
        }
      } else if (message.type === 'operation_update' && message.data?.event === 'batch_completion') {
        // Handle batch completion events from backend
        const { operation_type, wafers_failed, wafers_processed, batch_start, batch_count } = message.data;
        logger.log('Received batch completion event:', message.data);

        // Reset current wafer indicator and processing state since batch is done
        setCurrentWafer(0);
        setIsProcessing(false);

        // Store batch result
        setBatchResults(prev => [...prev, message.data]);

        // Handle step auto-advance based on operation type
        if (operation_type === 'pickup') {
          // Pickup complete (step 1) - auto-advance to step 2
          logger.log('Pickup operation complete, auto-advancing to next step');
          toast.success('Pickup complete! Advancing to next step...', { autoClose: 2000 });
          setActiveStep(prev => prev + 1);
        } else if (operation_type === 'drop') {
          // Check for failures
          if (wafers_failed && wafers_failed.length > 0) {
            logger.log(`Batch had ${wafers_failed.length} failed wafers:`, wafers_failed);
            setFailedWafers(wafers_failed);
            setShowErrorDialog(true);
            return;
          }

          // Step 8 (Move to Baking Tray) complete - show completion before advancing
          toast.success(
            'Step 8 complete! All wafers moved to baking tray.',
            { autoClose: 2000 }
          );

          // Delay batch advancement to let user see step 8 completion
          setTimeout(() => {
            // Use refs to get current values (avoids stale closure)
            if (currentBatchRef.current < totalBatchesRef.current - 1) {
              const completedBatch = currentBatchRef.current + 1;
              const nextBatch = currentBatchRef.current + 2;
              logger.log(`Batch ${completedBatch} complete, advancing to batch ${nextBatch}`);

              // Show batch completion toast
              toast.success(
                `Batch ${completedBatch} completed successfully! Starting batch ${nextBatch}...`,
                { autoClose: 4000 }
              );

              setCurrentBatch(prev => prev + 1);
              setActiveStep(0);
              setStepConfirmations({});
              // User will manually press pickup button to start next batch
            } else {
              // All batches complete
              logger.log('All batches complete!');
              toast.success(
                'All batches completed! Great job!',
                { autoClose: 5000 }
              );
              setShowAllComplete(true);
            }
          }, 2500);  // 2.5 second delay to show step 8 completion
        }
      } else if (message.type === 'operation_update' && message.data?.event === 'wafer_progress') {
        // Handle wafer progress updates
        const { wafer_num, wafer_index } = message.data;
        logger.log(`Wafer progress: ${wafer_num} (index ${wafer_index})`);
        setCurrentWafer(wafer_num);
        // Set processing state when first wafer starts
        if (wafer_index === 0 || wafer_num === 1) {
          setIsProcessing(true);
        }
      }
    });

    return () => {
      logger.log('Cleaning up WebSocket connections');
      messageUnsubscribe();
      disconnectUnsubscribe();
      clearInterval(connectionCheckInterval);
    };
  }, []);

  // Utility function to check robot connection status
  const isRobotConnected = useCallback(
    (robot) => {
      const robotKey = ROBOT_MAP[robot] || robot.toLowerCase();
      const isConnected = systemStatus[robotKey] === 'connected';

      logger.log('Robot connection check:', {
        robot: robot,
        normalizedKey: robotKey,
        status: systemStatus[robotKey],
        isConnected: isConnected,
      });

      return isConnected;
    },
    [systemStatus]
  );

  // Check if a step can be executed
  const canExecuteStep = useCallback(
    (stepIndex) => {
      // Disable all steps if WebSocket is not connected
      if (!wsConnected) {
        return false;
      }

      // Disable all steps while processing a batch operation
      if (isProcessing) {
        return false;
      }

      const step = steps[stepIndex];
      const robotConnected = isRobotConnected(step.robot);
      const confirmationRequired = !!step.confirm;
      const isConfirmed = stepConfirmations[stepIndex];

      return robotConnected && (!confirmationRequired || isConfirmed);
    },
    [isRobotConnected, stepConfirmations, isProcessing, wsConnected]
  );

  // Debug current state
  React.useEffect(() => {
    console.log('*** STATE DEBUG: Component state updated');
    console.log('*** STATE DEBUG: activeStep:', activeStep);
    console.log('*** STATE DEBUG: steps.length:', steps.length);
    console.log('*** STATE DEBUG: current step:', steps[activeStep]);
    console.log('*** STATE DEBUG: systemStatus:', systemStatus);
    console.log('*** STATE DEBUG: emergencyStopActive:', emergencyStopActive);
    if (activeStep < steps.length) {
      console.log('*** STATE DEBUG: robotConnected for current step:', isRobotConnected(steps[activeStep].robot));
      console.log('*** STATE DEBUG: canExecute for current step:', canExecuteStep(activeStep));
    }
  }, [activeStep, systemStatus, emergencyStopActive]);

  // Handle OT2 protocol execution
  const handleOT2Protocol = async () => {
    try {
      console.log('*** OT2 PROTOCOL DEBUG: handleOT2Protocol() called');
      console.log('*** OT2 PROTOCOL DEBUG: trayInfo:', trayInfo);
      console.log('*** OT2 PROTOCOL DEBUG: websocketService:', websocketService);

      logger.log('Starting OT2 protocol with tray info:', trayInfo);

      const message = {
        type: 'command',
        command_type: 'ot2_protocol',
        commandId: Date.now().toString(), // Add a unique ID for tracking
        data: trayInfo || {}, // Send tray info directly without additional nesting
      };

      console.log('*** OT2 PROTOCOL DEBUG: Prepared message:', message);
      console.log('*** OT2 PROTOCOL DEBUG: About to call websocketService.send()');

      // Make sure we're sending just the trayInfo without nesting it inside parameters
      websocketService.send(message);

      console.log('*** OT2 PROTOCOL DEBUG: websocketService.send() completed');

      // Update UI state to indicate the protocol is running
      setOt2Status('running');
      console.log('*** OT2 PROTOCOL DEBUG: OT2 status set to running');
    } catch (error) {
      console.error('*** OT2 PROTOCOL DEBUG: Error in handleOT2Protocol:', error);
      logger.error('Failed to start OT2 protocol:', error);
      setOt2Status('error');
      setLastError('Failed to start OT2 protocol: ' + (error.message || 'Unknown error'));
    }
  };

  // Handle emergency stop - IMMEDIATE execution without confirmation
  const handleEmergencyStop = useCallback(() => {
    logger.log('🚨 Emergency stop activated - immediate execution');

    // IMMEDIATE visual feedback - show stopping state
    setEmergencyStopStopping(true);

    // Send emergency stop command immediately
    websocketService.send({
      type: 'command',
      command_type: 'emergency_stop',
      data: {
        robots: {
          meca: systemStatus.meca === 'connected',
          ot2: systemStatus.ot2 === 'connected',
          arduino: systemStatus.arduino === 'connected',
        },
      },
    });

    logger.log('✅ Emergency stop command sent - robots should halt immediately');

    // Auto-clear stopping state after 3 seconds if no response received
    setTimeout(() => {
      setEmergencyStopStopping(false);
      setEmergencyStopActive(true);
      logger.log('⏱️ Emergency stop timeout - assuming completed');
    }, 3000);

  }, [systemStatus]);

  // Handle emergency stop reset - IMMEDIATE execution without confirmation
  const handleEmergencyReset = useCallback(() => {
    logger.log('🔄 Emergency stop reset requested - immediate execution');

    // Send reset command immediately
    websocketService.send({
      type: 'command',
      command_type: 'emergency_reset',
      data: {}
    });

    // Update local state
    setEmergencyStopActive(false);

    logger.log('✅ Emergency stop reset command sent');
  }, []);

  // Confirmation modal handlers
  const showConfirmation = (title, message, action, variant = 'primary') => {
    setConfirmationModal({
      isOpen: true,
      title,
      message,
      action,
      variant
    });
  };

  const handleConfirm = () => {
    if (confirmationModal.action) {
      confirmationModal.action();
    }
    setConfirmationModal({ isOpen: false, title: '', message: '', action: null, variant: 'primary' });
  };

  const handleConfirmationCancel = () => {
    setConfirmationModal({ isOpen: false, title: '', message: '', action: null, variant: 'primary' });
  };

  // Handle system pause with confirmation
  const handlePause = useCallback(() => {
    showConfirmation(
      'Pause System',
      'This will pause all active operations. Are you sure you want to continue?',
      () => {
        logger.log('System pause activated');
        setSystemPaused(true);
        setPauseReason('User requested pause');

        // Send pause command to backend with step information
        websocketService.send({
          type: 'command',
          command_type: 'pause_system',
          commandId: Date.now().toString(),
          data: {
            reason: 'User requested pause',
            current_step: activeStep,
            step_name: steps[activeStep].label
          },
        });
      },
      'warning'
    );
  }, [activeStep, steps]);

  // Handle system resume
  const handleResume = useCallback(() => {
    logger.log('System resume activated');
    setSystemPaused(false);
    setPauseReason('');
    setPausedOperations([]);

    // Send resume command to backend with step information
    websocketService.send({
      type: 'command',
      command_type: 'resume_system',
      commandId: Date.now().toString(),
      data: {
        current_step: activeStep,
        step_name: steps[activeStep].label
      },
    });
  }, [activeStep, steps]);

  // Handle step skipping
  const handleSkip = () => {
    logger.log(`Skipping step ${activeStep}`);
    websocketService.send({
      type: 'command',
      command_type: 'skip_step',
      data: { stepIndex: activeStep },
    });
    setActiveStep((prev) => (prev + 1 < steps.length ? prev + 1 : prev));
  };

  // Handle retry failed wafers from error dialog
  const handleRetryFailed = useCallback(() => {
    logger.log('Retrying failed wafers:', failedWafers);
    setShowErrorDialog(false);

    // Re-run pickup with only failed wafer indices
    const batchStart = currentBatch * 5;
    websocketService.send({
      type: 'command',
      command_type: 'meca_pickup',
      data: {
        start: batchStart,
        count: 5,
        retry_wafers: failedWafers
      }
    });

    // Reset to step 0 (pickup) for retry
    setActiveStep(0);
    setStepConfirmations({});
    setFailedWafers([]);
  }, [currentBatch, failedWafers]);

  // Handle skip to next batch from error dialog
  const handleSkipToNextBatch = useCallback(() => {
    logger.log('Skipping to next batch after failures');
    setShowErrorDialog(false);
    setFailedWafers([]);

    if (currentBatch < totalBatches - 1) {
      setCurrentBatch(prev => prev + 1);
      setActiveStep(0);
      setStepConfirmations({});
    } else {
      // This was the last batch
      setShowAllComplete(true);
    }
  }, [currentBatch, totalBatches]);

  // Handle finish all batches
  const handleFinishAllBatches = useCallback(() => {
    logger.log('Finishing all batches, clearing state');
    setShowAllComplete(false);

    // Clear localStorage
    localStorage.removeItem(BATCH_STORAGE_KEY);

    // Reset batch state
    setCurrentBatch(0);
    setBatchResults([]);

    // Navigate back to form
    navigate('/spreading/form');
  }, [navigate]);

  // Handle step execution
  const handlePress = async (stepIndex) => {
    try {
      console.log('*** HANDLE PRESS DEBUG: handlePress called with stepIndex:', stepIndex);
      console.log('*** HANDLE PRESS DEBUG: activeStep:', activeStep);
      console.log('*** HANDLE PRESS DEBUG: steps[stepIndex]:', steps[stepIndex]);
      console.log('*** HANDLE PRESS DEBUG: steps[stepIndex].label:', steps[stepIndex]?.label);

      logger.log(`Executing step ${stepIndex}: ${steps[stepIndex].label}`);

      if (stepIndex === 2) {
        console.log('*** HANDLE PRESS DEBUG: stepIndex === 2, calling handleOT2Protocol()');
        await handleOT2Protocol();
        console.log('*** HANDLE PRESS DEBUG: handleOT2Protocol() completed');
      } else if (steps[stepIndex].onClick) {
        console.log('*** HANDLE PRESS DEBUG: calling steps[stepIndex].onClick()');
        await steps[stepIndex].onClick();
        console.log('*** HANDLE PRESS DEBUG: steps[stepIndex].onClick() completed');
      } else {
        console.log('*** HANDLE PRESS DEBUG: No action for this step');
      }
    } catch (error) {
      console.error('*** HANDLE PRESS DEBUG: Error in handlePress:', error);
      logger.error(`Error executing step ${stepIndex}:`, error);
      setLastError(`Failed to execute step ${stepIndex + 1}`);
    }
  };

  // Handle confirmation changes
  const handleConfirmationChange = (stepIndex, checked) => {
    logger.log(`Confirmation for step ${stepIndex} changed to: ${checked}`);
    setStepConfirmations((prev) => ({
      ...prev,
      [stepIndex]: checked,
    }));
  };

  return (
    <div className='min-h-screen bg-gray-50'>
      <div className='max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8'>
        {/* Header Section */}
        <div className='bg-white rounded-lg shadow-lg p-6 mb-8'>
          <div className='flex justify-between items-center'>
            <h1 className='text-2xl font-bold text-gray-900'>Th-228 Spreading</h1>
            {trayInfo && (
              <div className='bg-blue-50 rounded-md p-3'>
                <div className='grid grid-cols-2 gap-4'>
                  <p className='text-sm text-gray-600'>
                    Tray: <span className='font-medium'>{trayInfo.trayNumber}</span>
                  </p>
                  <p className='text-sm text-gray-600'>
                    Vial: <span className='font-medium'>{trayInfo.vialNumber}</span>
                  </p>
                </div>
              </div>
            )}
          </div>
          {/* System Status Indicators */}
          {systemPaused && (
            <div className='mt-4 bg-orange-50 text-orange-700 px-4 py-2 rounded-md border border-orange-200'>
              <div className='flex items-center'>
                <span className='mr-2'>⏸️</span>
                <div>
                  <strong>
                    {pausedStepName ? `Step "${pausedStepName}" Paused` : 'System Paused'}
                  </strong>
                  {pauseReason && <span className='ml-2 text-sm'>- {pauseReason}</span>}
                  {pausedStepIndex >= 0 && (
                    <span className='ml-2 text-sm'>
                      (Step {pausedStepIndex + 1} of {steps.length})
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* WebSocket Connection Status */}
          {!wsConnected && (
            <div className='mt-4 bg-yellow-50 text-yellow-700 px-4 py-2 rounded-md border border-yellow-200'>
              <div className='flex items-center'>
                <span className='mr-2 animate-pulse'>&#9888;</span>
                <span>WebSocket disconnected - Step execution disabled until connection is restored</span>
              </div>
            </div>
          )}

          {/* Error Display */}
          {(connectionError || lastError) && (
            <div className='mt-4 bg-red-50 text-red-700 px-4 py-2 rounded-md'>
              {connectionError
                ? 'Unable to connect to backend server. Please check your connection and try again.'
                : lastError}
            </div>
          )}
        </div>

        {/* System Status Component */}
        <SystemStatus onStatusChange={handleStatusChange} />

        {/* Batch Progress */}
        <BatchProgress
          currentBatch={currentBatch}
          totalBatches={totalBatches}
          totalWafers={totalWafers}
          currentWafer={currentWafer}
        />

        {/* Progress Steps */}
        <ProgressSteps steps={steps} activeStep={activeStep} />

        {/* Active Step Content */}
        <div className='bg-white rounded-lg shadow-lg p-6 mb-6'>
          <StepContent
            step={steps[activeStep]}
            stepIndex={activeStep}
            robotConnected={isRobotConnected(steps[activeStep].robot)}
            canExecute={canExecuteStep(activeStep)}
            onPress={() => {
              console.log('*** BUTTON CLICK DEBUG: Button clicked!');
              console.log('*** BUTTON CLICK DEBUG: activeStep:', activeStep);
              console.log('*** BUTTON CLICK DEBUG: robotConnected:', isRobotConnected(steps[activeStep].robot));
              console.log('*** BUTTON CLICK DEBUG: canExecute:', canExecuteStep(activeStep));
              console.log('*** BUTTON CLICK DEBUG: emergencyStopActive:', emergencyStopActive);
              console.log('*** BUTTON CLICK DEBUG: About to call handlePress');
              handlePress(activeStep);
            }}
            onSkip={handleSkip}
            onConfirmationChange={(checked) => handleConfirmationChange(activeStep, checked)}
            confirmationChecked={stepConfirmations[activeStep] || false}
            disabled={emergencyStopActive}
            systemStatus={systemStatus}
          />
        </div>

        {/* Control Buttons */}
        <div className='flex flex-col sm:flex-row gap-4'>
          <EmergencyButton
            active={emergencyStopActive}
            stopping={emergencyStopStopping}
            onClick={handleEmergencyStop}
            disabled={emergencyStopActive}
            className='w-full sm:w-auto'
          />
          <ResetButton
            disabled={!emergencyStopActive}
            onClick={handleEmergencyReset}
            className='w-full sm:w-auto'
          />
          <PauseButton
            paused={systemPaused}
            onClick={handlePause}
            disabled={emergencyStopActive}
            className='w-full sm:w-auto'
          />
          <ResumeButton
            paused={systemPaused}
            onClick={handleResume}
            disabled={emergencyStopActive}
            className='w-full sm:w-auto'
          />
          <SecondaryButton onClick={() => navigate('/spreading/form')} className='w-full sm:w-auto'>
            Back to Form
          </SecondaryButton>
        </div>

        {/* Confirmation Modal */}
        <ConfirmationModal
          isOpen={confirmationModal.isOpen}
          onClose={handleConfirmationCancel}
          onConfirm={handleConfirm}
          title={confirmationModal.title}
          message={confirmationModal.message}
          variant={confirmationModal.variant}
          confirmText="OK"
          cancelText="Cancel"
        />

        {/* Batch Error Dialog */}
        <BatchErrorDialog
          isOpen={showErrorDialog}
          currentBatch={currentBatch}
          failedWafers={failedWafers}
          onRetry={handleRetryFailed}
          onSkip={handleSkipToNextBatch}
          onClose={() => setShowErrorDialog(false)}
        />

        {/* All Complete Dialog */}
        <AllCompleteDialog
          isOpen={showAllComplete}
          totalWafers={totalWafers}
          batchResults={batchResults}
          onFinish={handleFinishAllBatches}
          onClose={() => setShowAllComplete(false)}
        />
      </div>
    </div>
  );
};

export default SpreadingPage;
