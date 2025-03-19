// StatusIndicator.jsx
import React, { useMemo, useEffect } from 'react';
import logger from '../../utils/logger';

const StatusIndicator = ({ status, label }) => {
  // Enhanced status normalization with proper mapping
  const normalizedStatus = useMemo(() => {
    // Log the raw input
    logger.log('StatusIndicator beginning normalization:', {
      rawStatus: status,
      rawLabel: label
    });

    // Ensure we're working with a string and normalize it
    const rawStatusString = String(status || '').toLowerCase().trim();
    
    // Map potential variations to standard values
    const statusMap = {
      'connected': 'connected',
      'connecting': 'connecting',
      'disconnect': 'disconnected',
      'disconnected': 'disconnected',
      'unknown': 'disconnected',
      '': 'disconnected',
      'undefined': 'disconnected',
      'null': 'disconnected'
    };

    // Important: Check if the status exists in systemStatus before defaulting to disconnected
    const normalized = statusMap[rawStatusString] || 'disconnected';

    logger.log('StatusIndicator normalization result:', {
      input: rawStatusString,
      output: normalized,
      statusMapKeys: Object.keys(statusMap)
    });

    return normalized;
  }, [status]);

  // Get appropriate styles based on the normalized status
  const getStatusStyle = () => {
    switch (normalizedStatus) {
      case 'connected':
        return {
          container: 'bg-green-100 text-green-800 border border-green-200',
          dot: 'bg-green-500',
          text: 'text-green-600'
        };
      case 'connecting':
        return {
          container: 'bg-yellow-100 text-yellow-800 border border-yellow-200',
          dot: 'bg-yellow-500 animate-pulse',
          text: 'text-yellow-600'
        };
      case 'disconnected':
      default:
        return {
          container: 'bg-red-100 text-red-800 border border-red-200',
          dot: 'bg-red-500',
          text: 'text-red-600'
        };
    }
  };

  const styles = getStatusStyle();

  // Format the displayed status text
  const displayStatus = useMemo(() => {
    const statusText = {
      'connected': 'Connected',
      'connecting': 'Connecting...',
      'disconnected': 'Disconnected'
    }[normalizedStatus] || 'Unknown';

    logger.log('StatusIndicator display text:', {
      normalizedStatus,
      displayText: statusText,
      label
    });

    return statusText;
  }, [normalizedStatus, label]);

  return (
    <div className="flex items-center space-x-2">
      {label && (
        <span className="text-sm text-gray-600 font-medium">
          {label}
        </span>
      )}
      <span 
        className={`
          px-2 py-1 
          rounded-full 
          text-xs 
          font-medium 
          ${styles.container}
          transition-all 
          duration-200
        `}
      >
        {displayStatus}
      </span>
      <div 
        className={`
          w-3 h-3 
          rounded-full 
          ${styles.dot} 
          transition-all 
          duration-200
        `} 
      />
    </div>
  );
};

export default React.memo(StatusIndicator);