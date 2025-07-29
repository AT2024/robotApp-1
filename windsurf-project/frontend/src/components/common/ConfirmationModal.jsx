import React, { useState } from 'react';
import Dialog from './Dialog';
import Button from './Button';

const ConfirmationModal = ({
  isOpen,
  onClose,
  onConfirm,
  title = "Confirm Action",
  message = "Are you sure you want to proceed?",
  confirmText = "OK",
  cancelText = "Cancel",
  variant = "primary", // primary, danger, warning
  showInput = false,
  inputPlaceholder = "",
  inputLabel = "",
  requireInput = false,
  loading = false
}) => {
  const [inputValue, setInputValue] = useState("");
  const [inputError, setInputError] = useState("");

  const handleConfirm = () => {
    if (showInput && requireInput && !inputValue.trim()) {
      setInputError("This field is required");
      return;
    }
    
    onConfirm(showInput ? inputValue : true);
    
    // Reset state
    setInputValue("");
    setInputError("");
  };

  const handleCancel = () => {
    onClose();
    // Reset state
    setInputValue("");
    setInputError("");
  };

  const handleInputChange = (e) => {
    setInputValue(e.target.value);
    if (inputError) {
      setInputError("");
    }
  };

  return (
    <Dialog 
      isOpen={isOpen} 
      onClose={handleCancel} 
      title={title}
      size="md"
    >
      <div className="space-y-4">
        {/* Message */}
        <div className="text-gray-700">
          {typeof message === 'string' ? (
            <p>{message}</p>
          ) : (
            message
          )}
        </div>
        
        {/* Input field if needed */}
        {showInput && (
          <div>
            {inputLabel && (
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {inputLabel}
                {requireInput && <span className="text-red-500 ml-1">*</span>}
              </label>
            )}
            <input
              type="text"
              value={inputValue}
              onChange={handleInputChange}
              placeholder={inputPlaceholder}
              className={`w-full px-3 py-2 border rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors duration-200 ${
                inputError ? 'border-red-500' : 'border-gray-300'
              }`}
            />
            {inputError && (
              <p className="mt-1 text-sm text-red-600">{inputError}</p>
            )}
          </div>
        )}
        
        {/* Action buttons */}
        <div className="flex justify-end space-x-3 pt-4">
          <Button
            variant="outline"
            onClick={handleCancel}
            disabled={loading}
          >
            {cancelText}
          </Button>
          <Button
            variant={variant}
            onClick={handleConfirm}
            loading={loading}
          >
            {confirmText}
          </Button>
        </div>
      </div>
    </Dialog>
  );
};

export default ConfirmationModal;