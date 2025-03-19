// ProgressSteps.jsx
import React from 'react';

// ProgressSteps component receives steps array, current active step, and system status
const ProgressSteps = ({ steps, activeStep, systemStatus = {} }) => {
  // Safely check robot connection status by normalizing robot name and checking system status
  const getRobotStatus = (robotName) => {
    if (!systemStatus || !robotName) return false;
    const statusKey = robotName.toLowerCase();
    return systemStatus[statusKey] === 'connected';
  };

  return (
    <div className="mb-8">
      <h2 className="text-xl font-semibold text-navy mb-4">Process Steps</h2>
      <div className="relative bg-white p-6 rounded-lg shadow-card">
        <div className="flex items-center justify-between w-full">
          {steps.map((step, index) => (
            <React.Fragment key={index}>
              {/* Step Circle - Shows number and changes color based on status */}
              <div className="flex flex-col items-center relative z-10">
                <div className={`w-12 h-12 flex items-center justify-center rounded-full border-2 transition-all duration-200
                  ${index === activeStep 
                    ? getRobotStatus(step.robot)
                      ? 'bg-green-500 border-green-500 text-white'
                      : 'bg-blue-600 border-blue-600 text-white'
                    : index < activeStep 
                      ? 'bg-green-500 border-green-500 text-white'
                      : 'border-gray-300 text-gray-500'
                  }`}>
                  {index + 1}
                </div>
                <span className="text-xs mt-2 text-center w-20 text-navy font-medium">
                  {step.label}
                </span>
              </div>
              
              {/* Connector Line - Links steps together with appropriate colors */}
              {index < steps.length - 1 && (
                <div className="flex-1 mx-4">
                  <div className={`h-0.5 transition-colors duration-200
                    ${index < activeStep 
                      ? 'bg-green-500' 
                      : index === activeStep 
                        ? getRobotStatus(step.robot)
                          ? 'bg-green-500'
                          : 'bg-blue-600'
                        : 'bg-gray-300'
                    }`} 
                  />
                </div>
              )}
            </React.Fragment>
          ))}
        </div>
      </div>
    </div>
  );
};

// Export as default to fix the import issues
export default ProgressSteps;