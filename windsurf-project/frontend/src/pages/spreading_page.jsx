// spreading_page.jsx
import React, { useState, useEffect, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import websocketService from '../utils/services/websocketService';
import logger from '../utils/logger';
import { SystemStatus } from '../components/status';
import { ProgressSteps, StepContent } from '../components/steps';
import { EmergencyButton, SecondaryButton, PauseButton, ResumeButton } from '../components/buttons';
import { ConfirmationModal } from '../components/common';

const ROBOT_MAP = {
  MECA: 'meca',
  OT2: 'ot2',
  ARDUINO: 'arduino',
};

const SpreadingPage = () => {
  const location = useLocation();
  const navigate = useNavigate();

  // Core state management with meaningful initial values
  const [activeStep, setActiveStep] = useState(0);
  const [systemStatus, setSystemStatus] = useState({
    backend: 'disconnected',
    meca: 'disconnected',
    arduino: 'disconnected',
    ot2: 'disconnected',
  });
  const [trayInfo, setTrayInfo] = useState(null);
  const [emergencyStopActive, setEmergencyStopActive] = useState(false);
  const [stepConfirmations, setStepConfirmations] = useState({});
  const [ot2Status, setOt2Status] = useState('idle');
  const [connectionError, setConnectionError] = useState(false);
  const [lastError, setLastError] = useState(null);
  
  // Pause/Resume functionality state
  const [systemPaused, setSystemPaused] = useState(false);
  const [pausedOperations, setPausedOperations] = useState([]);
  const [pauseReason, setPauseReason] = useState('');
  
  // Confirmation modal state
  const [confirmationModal, setConfirmationModal] = useState({
    isOpen: false,
    title: '',
    message: '',
    action: null,
    variant: 'primary'
  });

  // Define workflow steps with their associated robot commands
  const steps = [
    {
      label: 'Create Pick Up',
      robot: 'MECA',
      status: 'waiting',
      hasPress: true,
      onClick: async () => {
        try {
          logger.log('Initiating MECA pickup operation');
          websocketService.send({
            type: 'command',
            command_type: 'meca_pickup',
            data: {},
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
          logger.log('Initiating move to baking tray');
          websocketService.send({
            type: 'command',
            command_type: 'meca_drop',
            data: {
              start: 0,
              count: 5,
              is_last_batch: true,
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

  // Set up WebSocket connection and message handling
  useEffect(() => {
    logger.log('Initializing WebSocket connection');
    websocketService.connect();

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
          }
        } else {
          logger.error('Command failed:', message.error);
          setLastError(message.error);
          if (message.error?.includes('timeout')) {
            setConnectionError(true);
          }
        }
      } else if (message.type === 'system_status_update') {
        // Handle system-wide status updates (like pause/resume broadcasts)
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
      }
    });

    return () => {
      logger.log('Cleaning up WebSocket connections');
      messageUnsubscribe();
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
      const step = steps[stepIndex];
      const robotConnected = isRobotConnected(step.robot);
      const confirmationRequired = !!step.confirm;
      const isConfirmed = stepConfirmations[stepIndex];

      return robotConnected && (!confirmationRequired || isConfirmed);
    },
    [isRobotConnected, stepConfirmations]
  );

  // Handle OT2 protocol execution
  const handleOT2Protocol = async () => {
    try {
      logger.log('Starting OT2 protocol with tray info:', trayInfo);

      // Make sure we're sending just the trayInfo without nesting it inside parameters
      websocketService.send({
        type: 'command',
        command_type: 'ot2_protocol',
        commandId: Date.now().toString(), // Add a unique ID for tracking
        data: trayInfo || {}, // Send tray info directly without additional nesting
      });

      // Update UI state to indicate the protocol is running
      setOt2Status('running');
    } catch (error) {
      logger.error('Failed to start OT2 protocol:', error);
      setOt2Status('error');
      setLastError('Failed to start OT2 protocol: ' + (error.message || 'Unknown error'));
    }
  };

  // Handle emergency stop with confirmation
  const handleEmergencyStop = useCallback(() => {
    showConfirmation(
      'Emergency Stop',
      'This will immediately stop all robot operations. This action cannot be undone. Are you sure?',
      () => {
        logger.log('Emergency stop activated');
        setEmergencyStopActive(true);
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
      },
      'danger'
    );
  }, [systemStatus]);

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
        
        // Send pause command to backend
        websocketService.send({
          type: 'command',
          command_type: 'pause_system',
          commandId: Date.now().toString(),
          data: {
            reason: 'User requested pause',
            pause_all_operations: true,
            current_step: activeStep
          },
        });
      },
      'warning'
    );
  }, [activeStep]);

  // Handle system resume
  const handleResume = useCallback(() => {
    logger.log('System resume activated');
    setSystemPaused(false);
    setPauseReason('');
    setPausedOperations([]);
    
    // Send resume command to backend
    websocketService.send({
      type: 'command',
      command_type: 'resume_system', 
      commandId: Date.now().toString(),
      data: {
        resume_all_operations: true,
        current_step: activeStep
      },
    });
  }, [activeStep]);

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

  // Handle step execution
  const handlePress = async (stepIndex) => {
    try {
      logger.log(`Executing step ${stepIndex}: ${steps[stepIndex].label}`);

      if (stepIndex === 2) {
        await handleOT2Protocol();
      } else if (steps[stepIndex].onClick) {
        await steps[stepIndex].onClick();
      }
    } catch (error) {
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
                  <strong>System Paused</strong>
                  {pauseReason && <span className='ml-2 text-sm'>- {pauseReason}</span>}
                </div>
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

        {/* Progress Steps */}
        <ProgressSteps steps={steps} activeStep={activeStep} />

        {/* Active Step Content */}
        <div className='bg-white rounded-lg shadow-lg p-6 mb-6'>
          <StepContent
            step={steps[activeStep]}
            stepIndex={activeStep}
            robotConnected={isRobotConnected(steps[activeStep].robot)}
            canExecute={canExecuteStep(activeStep)}
            onPress={() => handlePress(activeStep)}
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
            onClick={handleEmergencyStop}
            disabled={emergencyStopActive}
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
      </div>
    </div>
  );
};

export default SpreadingPage;
