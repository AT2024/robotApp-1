// components/config/ConfigField.jsx
import React, { useState } from 'react';
import { ChevronDown, ChevronRight, Edit2, Check, X } from 'lucide-react';

const ConfigField = ({ label, value, path, isEditing, onEdit, onChange, onSave, onCancel }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const isArray = Array.isArray(value);
  const isObject = typeof value === 'object' && value !== null && !isArray;

  // Utility function to format different types of values for display
  const getDisplayValue = () => {
    if (isArray) {
      if (!isExpanded) return `[${value.length} items]`;
      return JSON.stringify(value, null, 2);
    }
    if (isObject) {
      if (!isExpanded) return '{...}';
      return JSON.stringify(value, null, 2);
    }
    return String(value);
  };

  // Render edit mode interface
  const renderEditMode = () => (
    <div className="flex items-center gap-2 p-2 bg-white rounded-lg shadow-sm">
      <input
        className="flex-1 p-2 text-sm font-mono border rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
        defaultValue={typeof value === 'object' ? JSON.stringify(value) : value}
        onChange={(e) => onChange(path, e.target.value)}
      />
      <button 
        onClick={onSave}
        className="p-2 text-green-600 hover:bg-green-50 rounded-full transition-colors"
        aria-label="Save changes"
      >
        <Check className="w-4 h-4" />
      </button>
      <button 
        onClick={onCancel}
        className="p-2 text-red-600 hover:bg-red-50 rounded-full transition-colors"
        aria-label="Cancel changes"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );

  // Render display mode interface
  const renderDisplayMode = () => (
    <div className="flex items-center">
      {(isArray || isObject) && (
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="p-1 hover:bg-gray-100 rounded-md mr-2 transition-colors"
          aria-label={isExpanded ? "Collapse" : "Expand"}
        >
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-gray-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-gray-500" />
          )}
        </button>
      )}
      <span className="font-semibold text-gray-700">{label}:</span>
      <span className="ml-2 text-gray-600 whitespace-pre-wrap break-all">
        {getDisplayValue()}
      </span>
    </div>
  );

  return (
    <div className="group flex items-start gap-2 p-2 rounded-lg hover:bg-gray-50 transition-colors">
      <div className="flex-1 font-mono">
        {isEditing ? renderEditMode() : renderDisplayMode()}
      </div>
      {!isEditing && (
        <button
          onClick={() => onEdit(path)}
          className="opacity-0 group-hover:opacity-100 p-2 text-blue-600 hover:bg-blue-50 rounded-full transition-all"
          aria-label="Edit field"
        >
          <Edit2 className="w-4 h-4" />
        </button>
      )}
    </div>
  );
};

export default ConfigField;