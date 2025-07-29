// pages/ConfigPage.jsx
import React, { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { ConfigDisplay } from '../components/config';
import { Save, Loader } from 'lucide-react';
import configService from '../utils/services/configService';

// Logger for tracking component lifecycle and errors
const logger = {
  log: (message, data = '') => {
    const timestamp = new Date().toISOString();
    console.log(`[${timestamp}] ConfigPage: ${message}`, data ? data : '');
  },
  error: (message, error = '') => {
    const timestamp = new Date().toISOString();
    console.error(`[${timestamp}] ConfigPage Error: ${message}`, error ? error : '');
  },
};

const ConfigPage = () => {
  // State management for configuration data and UI state
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [configData, setConfigData] = useState(null);
  const [editedConfig, setEditedConfig] = useState(null);
  const [status, setStatus] = useState('connecting');
  const [editingPath, setEditingPath] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState(null);
  const { type } = useParams();

  // Handle editing a specific configuration field
  const handleEdit = (path) => {
    setEditingPath(path);
  };

  // Handle changes to configuration values
  const handleChange = (path, value) => {
    setEditedConfig((prev) => {
      const newConfig = { ...prev };
      const pathParts = path.split('.');
      let current = newConfig;

      // Navigate to the nested property
      for (let i = 0; i < pathParts.length - 1; i++) {
        current = current[pathParts[i]];
      }

      // Update the value at the specified path
      current[pathParts[pathParts.length - 1]] = value;
      return newConfig;
    });
  };

  // Handle saving configuration changes
  const handleSave = async () => {
    try {
      setIsSaving(true);
      await configService.saveConfig({
        type: 'save_config',
        config_type: type,
        data: editedConfig,
      });

      await configService.requestConfig(type);
      setEditingPath(null);
      setSaveMessage({
        type: 'success',
        message: 'Configuration saved successfully',
      });
    } catch (error) {
      logger.error('Save failed:', error);
      setSaveMessage({
        type: 'error',
        message: `Failed to save: ${error.message}`,
      });
    } finally {
      setIsSaving(false);
    }
  };

  // Handle canceling current edits
  const handleCancel = () => {
    setEditedConfig(configData);
    setEditingPath(null);
  };

  // Handle retrying connection
  const handleRetry = useCallback(() => {
    logger.log('Manual retry requested');
    setStatus('connecting');
    setError(null);
    setIsLoading(true);
    configService.disconnect();
  }, []);

  // Handle configuration updates from the server
  const handleConfigUpdate = useCallback((data) => {
    logger.log('Received config message:', data);

    if (data.type === 'error') {
      logger.error('Received error message:', data.message);
      setError(data.message);
      setStatus('error');
      setIsLoading(false);
      return;
    }

    try {
      const configContent = data.data?.content || data;

      // Special handling for OT2 config type
      if (type === 'ot2') {
        const plainConfig = JSON.parse(
          JSON.stringify(configContent, (key, value) => {
            if (typeof value === 'function') {
              console.warn(`Removing function property: ${key}`);
              return undefined;
            }
            return value;
          })
        );

        setConfigData(plainConfig);
        setEditedConfig(plainConfig);
      } else {
        setConfigData(configContent);
        setEditedConfig(configContent);
      }

      setIsLoading(false);
      setError(null);
      setStatus('connected');
    } catch (error) {
      logger.error('Error processing config:', error);
      setError('Failed to process configuration data');
      setStatus('error');
      setIsLoading(false);
    }
  }, [type]);

  // Setup connection and load initial data
  useEffect(() => {
    logger.log(`Initializing config page for type: ${type}`);
    let mounted = true;
    let connectionRetryCount = 0;
    const MAX_RETRIES = 3;
    const RETRY_DELAY = 2000;

    const setupConnection = async () => {
      try {
        setIsLoading(true);
        setError(null);
        await configService.connect(handleConfigUpdate);

        if (!mounted) return;

        // Removed 1-second delay for immediate startup responsiveness

        if (mounted) {
          const configResponse = await configService.requestConfig(type);
          handleConfigUpdate(configResponse);
        }
      } catch (error) {
        if (!mounted) return;
        
        if (connectionRetryCount < MAX_RETRIES) {
          connectionRetryCount++;
          setTimeout(setupConnection, RETRY_DELAY);
        } else {
          setError(`Failed to connect after ${MAX_RETRIES} attempts: ${error.message}`);
          setIsLoading(false);
        }
      }
    };

    setupConnection();
    return () => {
      mounted = false;
      configService.disconnect();
    };
  }, [type, handleConfigUpdate]);

  // Render loading state
  if (isLoading) {
    return (
      <div className="p-4">
        <div className="bg-white rounded-lg shadow-md">
          <div className="p-6">
            <div className="flex flex-col gap-4">
              <div className="flex items-center gap-3">
                <Loader className="w-5 h-5 animate-spin" />
                <p>Loading {type?.toUpperCase()} configuration...</p>
              </div>
              <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                <div className="h-full bg-blue-500 animate-pulse w-full" />
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Render error state
  if (status === 'error') {
    return (
      <div className="p-4">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex justify-between items-start">
            <div>
              <p className="font-semibold text-red-800 mb-1">Failed to load configuration</p>
              <p className="text-sm text-red-700">{error || 'Unknown error occurred'}</p>
            </div>
            <button 
              onClick={handleRetry}
              className="px-3 py-1 text-sm bg-white text-red-600 rounded-md hover:bg-red-50 transition-colors"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Render main configuration interface
  return (
    <div className="p-4">
      <div className="bg-white rounded-lg shadow-md">
        <div className="p-6">
          <div className="mb-4 flex justify-end">
            <button
              onClick={handleSave}
              disabled={
                isSaving ||
                !editedConfig ||
                JSON.stringify(configData) === JSON.stringify(editedConfig)
              }
              className={`flex items-center px-4 py-2 rounded-md transition-colors
                ${isSaving || !editedConfig || JSON.stringify(configData) === JSON.stringify(editedConfig)
                  ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                  : 'bg-blue-600 text-white hover:bg-blue-700'
                }`}
            >
              {isSaving ? (
                <Loader className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Save className="w-4 h-4 mr-2" />
              )}
              {isSaving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>

          {editedConfig ? (
            <ConfigDisplay
              configData={editedConfig}
              type={type}
              editingPath={editingPath}
              onEdit={handleEdit}
              onChange={handleChange}
              onSave={handleSave}
              onCancel={handleCancel}
            />
          ) : (
            <p className="text-gray-500">No configuration data available</p>
          )}
        </div>
      </div>

      {saveMessage && (
        <div className={`mt-4 p-4 rounded-lg ${
          saveMessage.type === 'error' 
            ? 'bg-red-50 border border-red-200 text-red-700'
            : 'bg-green-50 border border-green-200 text-green-700'
        }`}>
          {saveMessage.message}
        </div>
      )}
    </div>
  );
};

export default ConfigPage;