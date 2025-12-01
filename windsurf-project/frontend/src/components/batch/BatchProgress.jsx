import React from 'react';

/**
 * BatchProgress - Visual progress bar showing current batch and total progress
 * @param {number} currentBatch - Current batch index (0-based)
 * @param {number} totalBatches - Total number of batches
 * @param {number} totalWafers - Total number of wafers (default 55)
 * @param {number} currentWafer - Current wafer being processed (1-based, 0 when not processing)
 */
const BatchProgress = ({ currentBatch, totalBatches, totalWafers = 55, currentWafer = 0 }) => {
  const wafersProcessed = currentBatch * 5;
  const progressPercent = totalWafers > 0 ? (wafersProcessed / totalWafers) * 100 : 0;
  const currentBatchEnd = Math.min((currentBatch + 1) * 5, totalWafers);
  const batchStart = currentBatch * 5 + 1;
  const waferInBatch = currentWafer > 0 ? currentWafer - batchStart + 1 : 0;

  return (
    <div className="mb-4 p-4 bg-white border border-gray-200 rounded-lg shadow-sm">
      {/* Batch info */}
      <div className="flex justify-between items-center mb-2">
        <h3 className="text-lg font-semibold text-gray-900">
          Batch {currentBatch + 1} of {totalBatches}
        </h3>
        <span className="text-sm text-blue-600 font-medium">
          Wafers {currentBatch * 5 + 1} - {currentBatchEnd}
        </span>
      </div>

      {/* Progress bar */}
      <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
        <div
          className="bg-blue-600 h-full rounded-full transition-all duration-300 ease-out"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      {/* Progress text */}
      <div className="flex justify-between items-center mt-2">
        <span className="text-sm text-gray-600">
          {wafersProcessed} / {totalWafers} wafers completed
        </span>
        <span className="text-sm font-medium text-gray-700">
          {progressPercent.toFixed(0)}%
        </span>
      </div>

      {/* Current wafer indicator - only show when processing */}
      {currentWafer > 0 && waferInBatch > 0 && waferInBatch <= 5 && (
        <div className="mt-3 p-3 bg-blue-50 rounded-md border border-blue-200">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <div className="animate-spin h-4 w-4 border-2 border-blue-500 border-t-transparent rounded-full" />
              <span className="text-sm font-medium text-blue-800">
                Processing wafer {currentWafer}
              </span>
            </div>
            <span className="text-xs text-blue-600">
              {waferInBatch} of 5 in this batch
            </span>
          </div>
          {/* Mini progress bar for current batch operation */}
          <div className="mt-2 w-full bg-blue-200 rounded-full h-2">
            <div
              className="bg-blue-500 h-full rounded-full transition-all duration-300"
              style={{ width: `${(waferInBatch / 5) * 100}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default BatchProgress;
