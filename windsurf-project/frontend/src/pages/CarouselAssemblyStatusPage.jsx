import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import handleCarouselAssembly from '../utils/services/handleCarouselAssembly';
import websocketService from '../utils/services/websocketService';

const baseButtonClasses =
  'px-4 py-2 rounded-md font-medium focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200';

function CarouselAssemblyStatusPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryParams = new URLSearchParams(location.search);
  const carouselNumber = queryParams.get('carouselNumber');
  const trayNumber = queryParams.get('trayNumber');

  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [websocketStatus, setWebsocketStatus] = useState(
    websocketService.isConnected() ? 'connected' : 'disconnected'
  );

  // Setup WebSocket event listeners
  useEffect(() => {
    // Function to handle WebSocket status updates
    const handleWebsocketStatus = (message) => {
      if (message.type === 'status_update' && message.data?.type === 'backend') {
        setWebsocketStatus(message.data.status);
      }
      
      // Handle command responses specific to carousel assembly
      if (message.type === 'command_response' && 
          (message.command_type === 'carousel' || message.command_type === 'meca_carousel')) {
        if (message.status === 'success') {
          setStatus(message.message || 'Carousel assembly completed successfully!');
          setLoading(false);
        } else if (message.status === 'error') {
          setError(`Error: ${message.message || 'Unknown error occurred'}`);
          setLoading(false);
        }
      }
    };

    // Register the event listener
    const removeListener = websocketService.onMessage(handleWebsocketStatus);

    // Try to connect if not already connected
    if (!websocketService.isConnected()) {
      websocketService.connect()
        .then(() => {
          setWebsocketStatus('connected');
        })
        .catch((err) => {
          console.error('Failed to connect to WebSocket:', err);
          setWebsocketStatus('disconnected');
        });
    }

    // Clean up on unmount
    return () => {
      if (removeListener) removeListener();
    };
  }, []);

  const handleAssemble = async () => {
    setLoading(true);
    setError('');
    setStatus('Starting carousel assembly procedure...');

    try {
      // Default start at 0 and process 11 wafers as defined in the backend
      const response = await handleCarouselAssembly(carouselNumber, trayNumber);
      
      // The handleCarouselAssembly function will handle WebSocket and HTTP fallback
      // If we get here, it means we got a direct response (most likely HTTP)
      setStatus('Carousel assembly completed successfully!');
      
      if (response && response.message) {
        setStatus(response.message);
      }
    } catch (error) {
      console.error('Error during carousel assembly:', error);

      // Provide more detailed error information
      let errorMessage = 'Failed to assemble carousel';

      if (error.message) {
        errorMessage = error.message;
      }

      // Handle Axios errors specially
      if (error.isAxiosError) {
        if (error.response) {
          // The request was made and the server responded with a status code
          // that falls out of the range of 2xx
          errorMessage = `Server error (${error.response.status}): ${
            error.response.data?.message || 'Unknown server error'
          }`;
        } else if (error.request) {
          // The request was made but no response was received
          errorMessage = 'No response from server. Please check if the backend is running.';
        } else {
          // Something happened in setting up the request that triggered an Error
          errorMessage = `Request configuration error: ${error.message}`;
        }
      }

      setError(`Error: ${errorMessage}`);
      setStatus('');
    } finally {
      setLoading(false);
    }
  };

  const goBack = () => {
    navigate('/carousel-assembly');
  };

  return (
    <div className='flex flex-col items-center justify-center h-screen'>
      <h1 className='text-3xl font-semibold mb-4'>Carousel Assembly Status</h1>
      
      <div className='mb-4 text-sm'>
        <p className={`${websocketStatus === 'connected' ? 'text-green-600' : 'text-red-600'}`}>
          WebSocket: {websocketStatus}
        </p>
      </div>
      
      <p className='text-lg mb-2'>
        Carousel Number: <span className='font-medium'>{carouselNumber}</span>
      </p>
      <p className='text-lg mb-4'>
        Tray Number: <span className='font-medium'>{trayNumber}</span>
      </p>

      {error && (
        <div className='bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4'>
          {error}
        </div>
      )}

      {status && (
        <div className='bg-blue-100 border border-blue-400 text-blue-700 px-4 py-3 rounded mb-4'>
          {status}
        </div>
      )}

      <div className='flex space-x-4'>
        <button
          className={`${baseButtonClasses} bg-blue-600 text-white hover:bg-blue-700 focus:ring-blue-500`}
          onClick={handleAssemble}
          disabled={loading}>
          {loading ? 'Processing...' : 'Assemble Carousel Procedure'}
        </button>

        <button
          className={`${baseButtonClasses} bg-gray-300 text-gray-800 hover:bg-gray-400 focus:ring-gray-500`}
          onClick={goBack}
          disabled={loading}>
          Back
        </button>
      </div>
    </div>
  );
}

export default CarouselAssemblyStatusPage;