import React, { useState } from 'react';
import { Dialog, Input, Button } from './common';

const FormDialog = ({ isOpen, onClose, onSubmit }) => {
  const [formData, setFormData] = useState({
    trayNumber: '',
    vialNumber: '',
  });
  const [errors, setErrors] = useState({});

  const validateForm = () => {
    const newErrors = {};
    if (!formData.trayNumber.trim()) {
      newErrors.trayNumber = 'Tray number is required';
    }
    if (!formData.vialNumber.trim()) {
      newErrors.vialNumber = 'Vial number is required';
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));
    // Clear error when user starts typing
    if (errors[name]) {
      setErrors((prev) => ({
        ...prev,
        [name]: '',
      }));
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (validateForm()) {
      onSubmit(formData);
      onClose();
    }
  };

  return (
    <Dialog isOpen={isOpen} onClose={onClose} title='Enter Required Information'>
      <form onSubmit={handleSubmit} className='space-y-6'>
        <Input
          label='Tray Serial Number'
          id='trayNumber'
          name='trayNumber'
          value={formData.trayNumber}
          onChange={handleChange}
          error={!!errors.trayNumber}
          errorMessage={errors.trayNumber}
          placeholder='Enter tray serial number'
        />

        <Input
          label='Thorium Vial Number'
          id='vialNumber'
          name='vialNumber'
          value={formData.vialNumber}
          onChange={handleChange}
          error={!!errors.vialNumber}
          errorMessage={errors.vialNumber}
          placeholder='Enter thorium vial number'
        />

        <div className='flex justify-end space-x-4'>
          <Button variant='secondary' onClick={onClose}>
            Cancel
          </Button>
          <Button variant='primary' type='submit'>
            Continue
          </Button>
        </div>
      </form>
    </Dialog>
  );
};

export default FormDialog;
