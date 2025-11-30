import React from 'react';

/**
 * BatchProgress - Visual progress bar showing current batch and total progress
 * @param {number} currentBatch - Current batch index (0-based)
 * @param {number} totalBatches - Total number of batches
 * @param {number} totalWafers - Total number of wafers (default 55)
 */
const BatchProgress = ({ currentBatch, totalBatches, totalWafers = 55 }) => {
  const wafersProcessed = currentBatch * 5;
  const progressPercent = totalWafers > 0 ? (wafersProcessed / totalWafers) * 100 : 0;
  const currentBatchEnd = Math.min((currentBatch + 1) * 5, totalWafers);

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
    </div>
  );
};

export default BatchProgress;
