// components/common/buttons/index.jsx
import React from 'react';

const baseButtonClasses = "px-4 py-2 rounded-md font-medium focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200";

const PrimaryButton = ({ children, className = "", ...props }) => (
  <button
    className={`${baseButtonClasses} bg-blue-600 text-white hover:bg-blue-700 focus:ring-blue-500 ${className}`}
    {...props}
  >
    {children}
  </button>
);

const SecondaryButton = ({ children, className = "", ...props }) => (
  <button
    className={`${baseButtonClasses} bg-gray-200 text-gray-700 hover:bg-gray-300 focus:ring-gray-500 ${className}`}
    {...props}
  >
    {children}
  </button>
);

const EmergencyButton = ({ active, className = "", ...props }) => (
  <button
    className={`${baseButtonClasses} ${
      active 
        ? "bg-red-600 text-white"
        : "bg-red-500 text-white hover:bg-red-600"
    } focus:ring-red-500 ${className}`}
    {...props}
  >
    Emergency Stop
  </button>
);

const StepButton = ({ connected, ...props }) => (
  <button
    className={`${baseButtonClasses} ${
      connected
        ? "bg-green-600 text-white hover:bg-green-700"
        : "bg-gray-400 text-white"
    }`}
    {...props}
  >
    {connected ? "PRESS" : "Run"}
  </button>
);

const PauseButton = ({ paused, className = "", ...props }) => (
  <button
    className={`${baseButtonClasses} ${
      paused 
        ? "bg-gray-500 text-white cursor-not-allowed"
        : "bg-orange-500 text-white hover:bg-orange-600"
    } focus:ring-orange-500 ${className}`}
    disabled={paused}
    {...props}
  >
    ⏸️ Pause
  </button>
);

const ResumeButton = ({ paused, className = "", ...props }) => (
  <button
    className={`${baseButtonClasses} ${
      !paused 
        ? "bg-gray-500 text-white cursor-not-allowed"
        : "bg-green-500 text-white hover:bg-green-600"
    } focus:ring-green-500 ${className}`}
    disabled={!paused}
    {...props}
  >
    ▶️ Resume
  </button>
);

export { PrimaryButton, SecondaryButton, EmergencyButton, StepButton, PauseButton, ResumeButton };