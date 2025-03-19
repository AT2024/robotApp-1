// StepContent.jsx
import React, { useMemo } from 'react';
import { StatusIndicator } from '../status';

const StepContent = ({ 
  step, 
  stepIndex,
  systemStatus = {},
  canExecute,
  onPress,
  onSkip,
  onConfirmationChange,
  confirmationChecked = false,
  disabled
}) => {
  // Define mapping between display names and system status keys
  const ROBOT_MAP = {
    'MECA': 'meca',
    'OT2': 'ot2',
    'ARDUINO': 'arduino'
  };

  // Determine the current robot's status by looking up its normalized key in systemStatus
  const robotStatus = useMemo(() => {
    const robotKey = ROBOT_MAP[step.robot] || step.robot.toLowerCase();
    return systemStatus[robotKey] || 'disconnected';
  }, [step.robot, systemStatus]);

  return (
    <div>
      {/* Step header showing the current step number and label */}
      <h3 className="text-lg font-medium text-gray-900 mb-4">
        Step {stepIndex + 1}: {step.label}
      </h3>
      
      {/* Robot status display showing current connection state */}
      <div className="flex items-center space-x-2 mb-4">
        <span className="text-sm text-blue-600">Robot: {step.robot}</span>
        <StatusIndicator 
          status={robotStatus}
          label={step.robot}
        />
      </div>

      {/* Confirmation checkbox for steps that require user verification */}
      {step.confirm && (
        <div className="mb-4">
          <label className="flex items-center space-x-2">
            <input
              type="checkbox"
              checked={!!confirmationChecked}
              onChange={(e) => onConfirmationChange?.(e.target.checked)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-sm text-blue-600">{step.confirm}</span>
          </label>
        </div>
      )}

      {/* Action buttons for step control */}
      <div className="flex justify-end space-x-4">
        <button
          onClick={onSkip}
          className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
        >
          Skip
        </button>
        <button
          onClick={onPress}
          disabled={!canExecute || disabled || robotStatus !== 'connected'}
          className={`px-4 py-2 text-sm font-medium text-white rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 ${
            canExecute && !disabled && robotStatus === 'connected'
              ? 'bg-blue-600 hover:bg-blue-700'
              : 'bg-gray-300 cursor-not-allowed'
          }`}
        >
          Press
        </button>
      </div>
    </div>
  );
};

export default React.memo(StepContent);