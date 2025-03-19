import React, { useState } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  TextField,
  Button,
  Grid,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import { PlayArrow as StartIcon } from '@mui/icons-material';
import { ToastContainer, toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import StopButton from '../components/StopButton';
import LogsPanel from '../components/LogsPanel';
import api from '../services/api';

function ArduinoStepsPage() {
  const [formData, setFormData] = useState({
    command: '',
    steps: '',
    direction: 'clockwise',
  });

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await api.post('/api/arduino/command', formData);
      toast.success('Arduino command sent successfully');
    } catch (error) {
      toast.error(`Error sending command: ${error.message}`);
    }
  };

  return (
    <Box
      sx={{
        '& .MuiGrid-container': {
          spacing: 3,
        },
        '& .MuiGrid-item': {
          xs: 12,
          md: 6,
        },
        '& .MuiCard': {
          maxWidth: '100%',
        },
        '& .MuiCardContent': {
          padding: 2,
        },
        '& .MuiTypography-h4': {
          marginBottom: 2,
        },
        '& .MuiGrid-item form': {
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          padding: 2,
        },
        '& .MuiGrid-item form .MuiGrid-container': {
          spacing: 2,
        },
        '& .MuiGrid-item form .MuiGrid-item': {
          xs: 12,
        },
        '& .MuiGrid-item form .MuiTextField-root': {
          width: '100%',
        },
        '& .MuiGrid-item form .MuiFormControl-root': {
          width: '100%',
        },
        '& .MuiGrid-item form .MuiButton-root': {
          width: '100%',
          marginTop: 2,
        },
      }}>
      <Typography variant='h4' gutterBottom>
        Arduino Steps Control
      </Typography>

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <form onSubmit={handleSubmit}>
                <Grid container spacing={2}>
                  <Grid item xs={12}>
                    <TextField
                      fullWidth
                      label='Command'
                      name='command'
                      value={formData.command}
                      onChange={handleChange}
                      required
                    />
                  </Grid>
                  <Grid item xs={12}>
                    <TextField
                      fullWidth
                      label='Steps'
                      name='steps'
                      type='number'
                      value={formData.steps}
                      onChange={handleChange}
                      required
                    />
                  </Grid>
                  <Grid item xs={12}>
                    <FormControl fullWidth>
                      <InputLabel>Direction</InputLabel>
                      <Select
                        name='direction'
                        value={formData.direction}
                        onChange={handleChange}
                        label='Direction'>
                        <MenuItem value='clockwise'>Clockwise</MenuItem>
                        <MenuItem value='counterclockwise'>Counterclockwise</MenuItem>
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={6}>
                    <Button
                      type='submit'
                      variant='contained'
                      color='primary'
                      startIcon={<StartIcon />}
                      fullWidth>
                      Send Command
                    </Button>
                  </Grid>
                  <Grid item xs={6}>
                    <StopButton robotType='arduino' />
                  </Grid>
                </Grid>
              </form>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <LogsPanel />
        </Grid>
      </Grid>
    </Box>
  );
}

export default ArduinoStepsPage;
