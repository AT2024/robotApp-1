import React, { useState } from 'react';
import ConfigField from './ConfigField';
import ConfigList from './ConfigList';

const ConfigDisplay = ({ configData, type, editingPath, onEdit, onChange, onSave, onCancel }) => {
  const [selectedPath, setSelectedPath] = useState(null);

  const handleSelectConfig = (path) => {
    setSelectedPath(path);
    if (editingPath) {
      onCancel(); // Cancel any ongoing edits when selecting a new item
    }
  };

  // Get the selected configuration value
  const getSelectedConfig = () => {
    if (!selectedPath) return null;
    
    const pathParts = selectedPath.split('.');
    let current = configData;
    
    for (const part of pathParts) {
      current = current[part];
      if (current === undefined) return null;
    }
    
    return {
      key: pathParts[pathParts.length - 1],
      value: current,
      path: selectedPath
    };
  };

  const selectedConfig = getSelectedConfig();

  const renderSelectedConfig = () => {
    if (!selectedConfig) {
      return (
        <div className="text-center py-8 text-gray-500">
          Select a configuration item from the list to view and edit its details
        </div>
      );
    }

    return (
      <div>
        <h3 className="text-lg font-semibold text-gray-800 mb-4">
          {selectedConfig.path}
        </h3>
        <ConfigField
          label={selectedConfig.key}
          value={selectedConfig.value}
          path={selectedConfig.path}
          isEditing={editingPath === selectedConfig.path}
          onEdit={onEdit}
          onChange={onChange}
          onSave={onSave}
          onCancel={onCancel}
        />
      </div>
    );
  };

  return (
    <div className="bg-gray-50 p-6 rounded-lg">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-gray-800">
          {type?.toUpperCase()} Configuration
        </h2>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Config List Panel */}
        <div className="h-[600px]">
          <ConfigList 
            configData={configData}
            onSelectConfig={handleSelectConfig}
            selectedPath={selectedPath}
          />
        </div>

        {/* Config Detail Panel */}
        <div className="bg-white p-6 rounded-lg border h-[600px] overflow-y-auto">
          {renderSelectedConfig()}
        </div>
      </div>
    </div>
  );
};

export default ConfigDisplay;