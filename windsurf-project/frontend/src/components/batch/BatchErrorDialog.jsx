import React from 'react';
import Dialog from '../common/Dialog';
import Button from '../common/Button';

/**
 * BatchErrorDialog - Dialog to handle failed wafers with retry or skip options
 * @param {boolean} isOpen - Whether the dialog is open
 * @param {number} currentBatch - Current batch index (0-based)
 * @param {Array<number>} failedWafers - List of failed wafer indices
 * @param {function} onRetry - Callback when user clicks "Retry Failed"
 * @param {function} onSkip - Callback when user clicks "Skip & Continue"
 * @param {function} onClose - Callback to close the dialog
 */
const BatchErrorDialog = ({
  isOpen,
  currentBatch,
  failedWafers = [],
  onRetry,
  onSkip,
  onClose
}) => {
  // Convert wafer indices to 1-based wafer numbers for display
  const failedWaferNumbers = failedWafers.map(idx => idx + 1);

  return (
    <Dialog
      isOpen={isOpen}
      onClose={onClose || onSkip}
      title={`Batch ${currentBatch + 1} - Some Wafers Failed`}
      size="md"
    >
      <div className="space-y-4">
        {/* Warning icon and message */}
        <div className="flex items-start space-x-3">
          <div className="flex-shrink-0">
            <svg
              className="h-6 w-6 text-yellow-500"
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
          </div>
          <div>
            <p className="text-gray-700">
              <span className="font-semibold">{failedWafers.length}</span> wafer(s) failed to process:
            </p>
            <p className="mt-1 text-sm text-gray-500">
              Wafer{failedWafers.length > 1 ? 's' : ''}: {failedWaferNumbers.join(', ')}
            </p>
          </div>
        </div>

        {/* Action description */}
        <div className="text-sm text-gray-600 bg-gray-50 p-3 rounded-md">
          <p className="mb-2">
            <strong>Retry Failed:</strong> Re-run the sequence for only the failed wafers.
          </p>
          <p>
            <strong>Skip & Continue:</strong> Move to the next batch without retrying.
          </p>
        </div>

        {/* Action buttons */}
        <div className="flex justify-end space-x-3 pt-2">
          <Button
            variant="secondary"
            onClick={onSkip}
          >
            Skip & Continue
          </Button>
          <Button
            variant="primary"
            onClick={onRetry}
          >
            Retry Failed Wafers
          </Button>
        </div>
      </div>
    </Dialog>
  );
};

export default BatchErrorDialog;
