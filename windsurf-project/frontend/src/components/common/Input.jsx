import React from 'react';

const Input = ({ 
  type = "text",
  value,
  onChange,
  placeholder,
  className = "",
  disabled = false,
  required = false,
  error = false,
  errorMessage = "",
  label = "",
  id,
  ...props 
}) => {
  const baseClasses = "w-full px-3 py-2 border rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors duration-200";
  
  const stateClasses = error 
    ? "border-red-500 text-red-900 placeholder-red-400 focus:ring-red-500 focus:border-red-500"
    : "border-gray-300 text-gray-900 placeholder-gray-400";
    
  const disabledClasses = disabled 
    ? "bg-gray-100 cursor-not-allowed opacity-60"
    : "bg-white";

  return (
    <div className="w-full">
      {label && (
        <label htmlFor={id} className="block text-sm font-medium text-gray-700 mb-1">
          {label}
          {required && <span className="text-red-500 ml-1">*</span>}
        </label>
      )}
      
      <input
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        disabled={disabled}
        required={required}
        id={id}
        className={`${baseClasses} ${stateClasses} ${disabledClasses} ${className}`}
        {...props}
      />
      
      {error && errorMessage && (
        <p className="mt-1 text-sm text-red-600">{errorMessage}</p>
      )}
    </div>
  );
};

export default Input;