import React from 'react';

const Dialog = ({ 
  isOpen, 
  onClose, 
  title, 
  children, 
  className = "",
  size = "md" 
}) => {
  if (!isOpen) return null;

  const sizeClasses = {
    sm: "max-w-md",
    md: "max-w-lg", 
    lg: "max-w-2xl",
    xl: "max-w-4xl"
  };

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center overflow-x-hidden overflow-y-auto outline-none focus:outline-none bg-black bg-opacity-50"
      onClick={handleBackdropClick}
    >
      <div className={`relative w-auto mx-auto my-6 ${sizeClasses[size]}`}>
        <div className={`relative flex flex-col w-full bg-white border-0 rounded-lg shadow-lg outline-none focus:outline-none ${className}`}>
          {/* Header */}
          {title && (
            <div className="flex items-start justify-between p-5 border-b border-solid border-gray-200 rounded-t">
              <h3 className="text-xl font-semibold text-gray-900">{title}</h3>
              <button
                className="p-1 ml-auto bg-transparent border-0 text-gray-400 hover:text-gray-600 text-xl leading-none font-semibold outline-none focus:outline-none"
                onClick={onClose}
              >
                ×
              </button>
            </div>
          )}
          
          {/* Body */}
          <div className="relative p-6 flex-auto">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dialog;