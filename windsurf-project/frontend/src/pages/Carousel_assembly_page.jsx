import React, { useState } from 'react';
import axios from 'axios';
import { FormContainer, FormInput } from '../components/form';
import { PrimaryButton } from '../components/buttons';
import { useNavigate } from 'react-router-dom';
import handleDismantle from '../handleDismantle';

const CarouselAssemblyPage = () => {
  // Combine the state into a single formData object, similar to SpreadingFormPage
  const [formData, setFormData] = useState({
    carouselNumber: '',
    trayNumber: ''
  });
  const [status, setStatus] = useState('');
  const [showDismantleBtn, setShowDismantleBtn] = useState(false);
  const [error, setError] = useState('');

  // Unified change handler, similar to SpreadingFormPage
  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));
    setError('');
  };

  const navigate = useNavigate();

  // Check status function now integrated into form submission
  const handleSubmit = (e) => {
    e.preventDefault();

    // Form validation
    if (!formData.carouselNumber.trim() || !formData.trayNumber.trim()) {
      setError('Both fields are required');
      return;
    }

    // Navigate to the new page
    navigate(`/carousel-assembly-status?carouselNumber=${formData.carouselNumber}&trayNumber=${formData.trayNumber}`);
  };

  return (
    <FormContainer 
      title="Carousel Assembly" 
      onSubmit={handleSubmit}
      error={error}
    >
      <FormInput
        label="Carousel Number"
        id="carouselNumber"
        name="carouselNumber"
        value={formData.carouselNumber}
        onChange={handleChange}
        placeholder="Enter carousel number"
      />
      
      <FormInput
        label="Tray Number"
        id="trayNumber"
        name="trayNumber"
        value={formData.trayNumber}
        onChange={handleChange}
        placeholder="Enter tray number"
      />
      
      <PrimaryButton type="submit">
        Check Tray & Carousel Status
      </PrimaryButton>

      {status && (
        <div className="mt-4 text-sm text-gray-700">
          {status}
        </div>
      )}
      
      {showDismantleBtn && (
        <div className="mt-4">
          <PrimaryButton onClick={() => {
              handleDismantle(formData.trayNumber);
              }}>
            Dismantling a carousel
          </PrimaryButton>
        </div>
      )}
    </FormContainer>
  );
};

export default CarouselAssemblyPage;
