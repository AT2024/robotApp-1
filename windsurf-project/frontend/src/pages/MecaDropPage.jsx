import React, { useState } from 'react';
import { Box, Card, CardContent, Typography, TextField, Button, Grid } from '@mui/material';
import { PlayArrow as StartIcon } from '@mui/icons-material';
import { ToastContainer, toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import StopButton from '../components/StopButton';
import LogsPanel from '../components/LogsPanel';
import api from '../services/api';

function MecaDropPage() {
  const [formData, setFormData] = useState({
    position: '',
    height: '',
    speed: '',
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
      await api.post('/api/meca/drop', formData);
      toast.success('Drop operation started');
    } catch (error) {
      toast.error(`Error starting drop: ${error.message}`);
    }
  };

  return (
    <Box
      sx={{
        '& .MuiGrid-item': {
          padding: '16px',
        },
      }}>
      <Typography variant='h4' gutterBottom>
        Meca Drop Control
      </Typography>

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Card
            sx={{
              maxWidth: '100%',
            }}>
            <CardContent>
              <form onSubmit={handleSubmit}>
                <Grid container spacing={2}>
                  <Grid item xs={12}>
                    <TextField
                      fullWidth
                      label='Position'
                      name='position'
                      type='number'
                      value={formData.position}
                      onChange={handleChange}
                      required
                      sx={{
                        '& .MuiInputBase-input': {
                          padding: '10px',
                        },
                      }}
                    />
                  </Grid>
                  <Grid item xs={12}>
                    <TextField
                      fullWidth
                      label='Height (mm)'
                      name='height'
                      type='number'
                      value={formData.height}
                      onChange={handleChange}
                      required
                      sx={{
                        '& .MuiInputBase-input': {
                          padding: '10px',
                        },
                      }}
                    />
                  </Grid>
                  <Grid item xs={12}>
                    <TextField
                      fullWidth
                      label='Speed (mm/s)'
                      name='speed'
                      type='number'
                      value={formData.speed}
                      onChange={handleChange}
                      required
                      sx={{
                        '& .MuiInputBase-input': {
                          padding: '10px',
                        },
                      }}
                    />
                  </Grid>
                  <Grid item xs={6}>
                    <Button
                      type='submit'
                      variant='contained'
                      color='primary'
                      startIcon={<StartIcon />}
                      fullWidth
                      sx={{
                        '& .MuiButton-startIcon': {
                          margin: '0 8px',
                        },
                      }}>
                      Start
                    </Button>
                  </Grid>
                  <Grid item xs={6}>
                    <StopButton robotType='meca' />
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

export default MecaDropPage;
