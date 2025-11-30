import React from 'react';
import Dialog from '../common/Dialog';
import Button from '../common/Button';

/**
 * AllCompleteDialog - Success dialog when all batches are complete
 * @param {boolean} isOpen - Whether the dialog is open
 * @param {number} totalWafers - Total number of wafers processed
 * @param {Array} batchResults - Array of batch result objects
 * @param {function} onFinish - Callback when user clicks "Finish"
 * @param {function} onClose - Callback to close the dialog
 */
const AllCompleteDialog = ({
  isOpen,
  totalWafers = 55,
  batchResults = [],
  onFinish,
  onClose
}) => {
  // Calculate totals from batch results
  const totalSuccess = batchResults.reduce(
    (sum, result) => sum + (result.wafers_processed || 0),
    0
  );
  const totalFailed = batchResults.reduce(
    (sum, result) => sum + (result.wafers_failed?.length || 0),
    0
  );
  const successRate = totalWafers > 0
    ? ((totalSuccess / totalWafers) * 100).toFixed(1)
    : 0;

  return (
    <Dialog
      isOpen={isOpen}
      onClose={onClose || onFinish}
      title="All Wafers Complete!"
      size="md"
    >
      <div className="space-y-4">
        {/* Success icon and message */}
        <div className="flex items-center justify-center">
          <div className="rounded-full bg-green-100 p-3">
            <svg
              className="h-12 w-12 text-green-600"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </div>
        </div>

        {/* Summary */}
        <div className="text-center">
          <h3 className="text-xl font-semibold text-gray-900">
            Processing Complete
          </h3>
          <p className="mt-2 text-gray-600">
            Successfully processed {totalSuccess} of {totalWafers} wafers
          </p>
        </div>

        {/* Statistics */}
        <div className="bg-gray-50 rounded-lg p-4 space-y-2">
          <div className="flex justify-between">
            <span className="text-gray-600">Total Batches:</span>
            <span className="font-medium text-gray-900">{batchResults.length}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-600">Wafers Processed:</span>
            <span className="font-medium text-green-600">{totalSuccess}</span>
          </div>
          {totalFailed > 0 && (
            <div className="flex justify-between">
              <span className="text-gray-600">Wafers Failed:</span>
              <span className="font-medium text-red-600">{totalFailed}</span>
            </div>
          )}
          <div className="flex justify-between border-t pt-2 mt-2">
            <span className="text-gray-600">Success Rate:</span>
            <span className={`font-semibold ${
              parseFloat(successRate) >= 95 ? 'text-green-600' :
              parseFloat(successRate) >= 80 ? 'text-yellow-600' : 'text-red-600'
            }`}>
              {successRate}%
            </span>
          </div>
        </div>

        {/* Action button */}
        <div className="flex justify-center pt-2">
          <Button
            variant="success"
            size="lg"
            onClick={onFinish}
          >
            Finish & Return to Form
          </Button>
        </div>
      </div>
    </Dialog>
  );
};

export default AllCompleteDialog;
