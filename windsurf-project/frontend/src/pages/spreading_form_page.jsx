import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PrimaryButton } from '../components/buttons';
import { FormContainer, FormInput } from '../components/form';


const SpreadingFormPage = () => {
  const navigate = useNavigate();
  const [formData, setFormData] = useState({
    trayNumber: '',
    vialNumber: '',
  });
  const [error, setError] = useState('');

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));
    setError('');
  };

  const handleSubmit = (e) => {
    e.preventDefault();

    if (!formData.trayNumber.trim() || !formData.vialNumber.trim()) {
      setError('Both fields are required');
      return;
    }

    // Navigate to spreading page with form data
    navigate('/spreading', { state: { trayInfo: formData } });
  };

  return (
    <FormContainer 
      title="Enter Required Information" 
      onSubmit={handleSubmit}
      error={error}
    >
      <FormInput
        label="Tray Serial Number"
        id="trayNumber"
        name="trayNumber"
        value={formData.trayNumber}
        onChange={handleChange}
        placeholder="Enter tray serial number"
      />
      
      <FormInput
        label="Thorium Vial Number"
        id="vialNumber"
        name="vialNumber"
        value={formData.vialNumber}
        onChange={handleChange}
        placeholder="Enter thorium vial number"
      />
      
      <PrimaryButton type="submit">
        Continue
      </PrimaryButton>
    </FormContainer>
  );
};

export default SpreadingFormPage;
