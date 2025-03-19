import React from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from './pages/Layout';

const WelcomePage = () => {
  const navigate = useNavigate();

  const handleSpreadingClick = () => {
    navigate('/spreading');
  };

  return (
    <Layout>
      <div className="h-screen flex flex-col justify-center items-center bg-gray-100">
        <h1 className="text-4xl font-bold text-gray-800 text-center">Welcome to the Robotic Control Panel</h1>
        <p className="mt-4 text-lg text-gray-600">Please select the process you want to perform on the left bar:</p>
        
      </div>
    </Layout>
  );
};

export default WelcomePage;
