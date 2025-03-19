// components/common/form/FormContainer.jsx
import React from 'react';

const FormContainer = ({ title, children, onSubmit, error }) => {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-50">
      <div className="w-full max-w-md bg-white rounded-lg shadow-md p-8">
        <h2 className="text-2xl font-semibold mb-6 text-center">{title}</h2>
        
        <form onSubmit={onSubmit} className="space-y-4">
          {children}
          
          {error && (
            <div className="bg-red-50 border border-red-400 text-red-700 px-4 py-3 rounded">
              {error}
            </div>
          )}
        </form>
      </div>
    </div>
  );
};

export default FormContainer;