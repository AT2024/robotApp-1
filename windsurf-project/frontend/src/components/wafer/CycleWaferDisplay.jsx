import React from 'react';

/**
 * CycleWaferDisplay - Shows 5 wafers for the current cycle with visual status
 *
 * @param {number} currentWafer - Current wafer number being processed (1-55, 0 when idle)
 * @param {number} cycleStart - First wafer in current cycle (1-based)
 * @param {number} cycleCount - Number of wafers per cycle (default 5)
 * @param {string} currentOperation - Current operation type (pickup/drop/carousel)
 * @param {number} progress - Progress percentage within current operation
 * @param {number} totalWafers - Total wafers to process (default 55)
 * @param {Array} completedWafers - Array of completed wafer numbers
 * @param {Array} failedWafers - Array of failed wafer numbers
 */
const CycleWaferDisplay = ({
  currentWafer = 0,
  cycleStart = 1,
  cycleCount = 5,
  currentOperation = '',
  progress = 0,
  totalWafers = 55,
  completedWafers = [],
  failedWafers = []
}) => {
  // Calculate cycle info from current wafer
  const cycleNumber = currentWafer > 0
    ? Math.floor((currentWafer - 1) / cycleCount) + 1
    : Math.floor((cycleStart - 1) / cycleCount) + 1;

  const totalCycles = Math.ceil(totalWafers / cycleCount);

  // Calculate wafer positions for current cycle
  const cycleStartWafer = (cycleNumber - 1) * cycleCount + 1;
  const cycleEndWafer = Math.min(cycleStartWafer + cycleCount - 1, totalWafers);

  // Build wafer slots for current cycle
  const waferSlots = [];
  for (let i = cycleStartWafer; i <= cycleStartWafer + cycleCount - 1; i++) {
    if (i > totalWafers) break;
    waferSlots.push(i);
  }

  // Determine wafer status and style
  const getWaferStatus = (waferNum) => {
    if (failedWafers.includes(waferNum)) return 'failed';
    if (completedWafers.includes(waferNum)) return 'complete';
    if (waferNum === currentWafer) return 'active';
    if (waferNum < currentWafer || completedWafers.some(w => w > waferNum)) return 'complete';
    return 'pending';
  };

  const getWaferStyles = (status) => {
    const baseStyles = 'w-12 h-12 rounded-full flex items-center justify-center font-bold text-sm transition-all duration-300 border-2';

    switch (status) {
      case 'pending':
        return `${baseStyles} bg-gray-100 text-gray-400 border-gray-300`;
      case 'active':
        return `${baseStyles} bg-blue-500 text-white border-blue-600 shadow-lg shadow-blue-500/50 animate-pulse`;
      case 'complete':
        return `${baseStyles} bg-green-500 text-white border-green-600`;
      case 'failed':
        return `${baseStyles} bg-red-500 text-white border-red-600`;
      default:
        return `${baseStyles} bg-gray-100 text-gray-400 border-gray-300`;
    }
  };

  // Format operation name for display
  const formatOperation = (op) => {
    if (!op) return 'Idle';
    return op.charAt(0).toUpperCase() + op.slice(1).replace(/_/g, ' ');
  };

  // Calculate wafer position within cycle
  const waferInCycle = currentWafer > 0 ? ((currentWafer - 1) % cycleCount) + 1 : 0;

  return (
    <div className="bg-white rounded-lg shadow-lg p-6 mb-6">
      {/* Header with cycle info */}
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-bold text-gray-900">
          Cycle {cycleNumber} of {totalCycles}
        </h3>
        <span className="text-sm font-medium px-3 py-1 rounded-full bg-blue-100 text-blue-700">
          Wafers {cycleStartWafer} - {cycleEndWafer}
        </span>
      </div>

      {/* Wafer slots display */}
      <div className="flex justify-center items-center gap-4 mb-4">
        {waferSlots.map((waferNum) => {
          const status = getWaferStatus(waferNum);
          return (
            <div key={waferNum} className="flex flex-col items-center">
              <div className={getWaferStyles(status)}>
                {waferNum}
              </div>
              <span className="text-xs text-gray-500 mt-1 capitalize">
                {status === 'active' ? currentOperation || 'active' : status}
              </span>
            </div>
          );
        })}
      </div>

      {/* Current operation status */}
      {currentWafer > 0 && (
        <div className="mt-4 p-4 bg-blue-50 rounded-lg border border-blue-200">
          <div className="flex justify-between items-center">
            <div className="flex items-center gap-3">
              {/* Animated spinner */}
              <div className="relative">
                <div className="w-8 h-8 border-4 border-blue-200 rounded-full"></div>
                <div className="absolute top-0 left-0 w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
              </div>
              <div>
                <p className="font-semibold text-blue-800">
                  Wafer {currentWafer} - {formatOperation(currentOperation)}
                </p>
                <p className="text-sm text-blue-600">
                  {waferInCycle} of {Math.min(cycleCount, cycleEndWafer - cycleStartWafer + 1)} in this cycle
                </p>
              </div>
            </div>
            <div className="text-right">
              <span className="text-2xl font-bold text-blue-700">
                {progress.toFixed(0)}%
              </span>
            </div>
          </div>

          {/* Progress bar */}
          <div className="mt-3 w-full bg-blue-200 rounded-full h-2 overflow-hidden">
            <div
              className="bg-blue-500 h-full rounded-full transition-all duration-300 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Idle state */}
      {currentWafer === 0 && (
        <div className="mt-4 p-4 bg-gray-50 rounded-lg border border-gray-200 text-center">
          <p className="text-gray-500">Ready for next operation</p>
        </div>
      )}
    </div>
  );
};

export default CycleWaferDisplay;
