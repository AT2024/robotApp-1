import React, { useState } from 'react';
import { Search, ChevronDown } from 'lucide-react';

const ConfigList = ({ configData, onSelectConfig, selectedPath }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  
  // Convert config object to array of entries with path
  const flattenConfig = (obj, parentPath = '') => {
    return Object.entries(obj).reduce((acc, [key, value]) => {
      const currentPath = parentPath ? `${parentPath}.${key}` : key;
      
      if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
        return [...acc, ...flattenConfig(value, currentPath)];
      }
      
      return [...acc, {
        path: currentPath,
        key,
        value: Array.isArray(value) ? `[${value.length} items]` : String(value)
      }];
    }, []);
  };

  const configItems = flattenConfig(configData);
  
  // Filter items based on search term
  const filteredItems = configItems.filter(item => 
    item.path.toLowerCase().includes(searchTerm.toLowerCase()) ||
    String(item.value).toLowerCase().includes(searchTerm.toLowerCase())
  );

  const selectedItem = configItems.find(item => item.path === selectedPath);

  return (
    <div className="relative">
      {/* Dropdown Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between p-3 bg-white border rounded-lg hover:bg-gray-50 transition-colors"
      >
        <span className="truncate">
          {selectedItem ? selectedItem.path : 'Select configuration...'}
        </span>
        <ChevronDown className={`w-5 h-5 text-gray-500 transition-transform ${isOpen ? 'transform rotate-180' : ''}`} />
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div className="absolute z-10 w-full mt-1 bg-white border rounded-lg shadow-lg max-h-96 overflow-hidden">
          {/* Search Bar */}
          <div className="p-2 border-b sticky top-0 bg-white">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Search configurations..."
                className="w-full pl-9 pr-4 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                onClick={(e) => e.stopPropagation()}
              />
            </div>
          </div>

          {/* Options List */}
          <div className="overflow-y-auto max-h-72">
            {filteredItems.map((item) => (
              <button
                key={item.path}
                onClick={() => {
                  onSelectConfig(item.path);
                  setIsOpen(false);
                }}
                className={`w-full text-left px-4 py-2 hover:bg-gray-50 transition-colors ${
                  selectedPath === item.path ? 'bg-blue-50' : ''
                }`}
              >
                <div className="font-medium text-gray-900 truncate">{item.path}</div>
                <div className="text-sm text-gray-500 truncate">{item.value}</div>
              </button>
            ))}
            
            {filteredItems.length === 0 && (
              <div className="p-4 text-center text-gray-500">
                No configurations found matching "{searchTerm}"
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ConfigList;