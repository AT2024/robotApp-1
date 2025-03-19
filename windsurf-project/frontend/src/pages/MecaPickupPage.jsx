// import React, { useState } from 'react';
// import { Box, Card, CardContent, Typography, TextField, Button, Grid } from '@mui/material';
// import { PlayArrow as StartIcon } from '@mui/icons-material';
// import { ToastContainer, toast } from 'react-toastify';
// import 'react-toastify/dist/ReactToastify.css';
// import StopButton from '../components/StopButton';
// import LogsPanel from '../components/LogsPanel';
// import api from '../services/api';

// function MecaPickupPage() {
//   const [formData, setFormData] = useState({
//     trayNumber: '',
//     bottleNumber: '',
//     height: '',
//   });

//   const handleChange = (e) => {
//     setFormData({
//       ...formData,
//       [e.target.name]: e.target.value,
//     });
//   };

//   const handleSubmit = async (e) => {
//     e.preventDefault();
//     try {
//       await api.post('/api/meca/pickup', formData);
//       toast.success('Pickup operation started');
//     } catch (error) {
//       toast.error(`Error starting pickup: ${error.message}`);
//     }
//   };

//   return (
//     <Box
//       sx={{
//         '& .MuiGrid-item': {
//           padding: '16px',
//         },
//       }}>
//       <Typography variant='h4' gutterBottom>
//         Meca Pickup Control
//       </Typography>

//       <Grid container spacing={3}>
//         <Grid item xs={12} md={6}>
//           <Card
//             sx={{
//               maxWidth: '100%',
//             }}>
//             <CardContent>
//               <form onSubmit={handleSubmit}>
//                 <Grid container spacing={2}>
//                   <Grid item xs={12}>
//                     <TextField
//                       fullWidth
//                       label='Tray Number'
//                       name='trayNumber'
//                       type='number'
//                       value={formData.trayNumber}
//                       onChange={handleChange}
//                       required
//                       sx={{
//                         '& .MuiInputLabel-root': {
//                           fontSize: '16px',
//                         },
//                         '& .MuiInputBase-input': {
//                           fontSize: '16px',
//                         },
//                       }}
//                     />
//                   </Grid>
//                   <Grid item xs={12}>
//                     <TextField
//                       fullWidth
//                       label='Bottle Number'
//                       name='bottleNumber'
//                       type='number'
//                       value={formData.bottleNumber}
//                       onChange={handleChange}
//                       required
//                       sx={{
//                         '& .MuiInputLabel-root': {
//                           fontSize: '16px',
//                         },
//                         '& .MuiInputBase-input': {
//                           fontSize: '16px',
//                         },
//                       }}
//                     />
//                   </Grid>
//                   <Grid item xs={12}>
//                     <TextField
//                       fullWidth
//                       label='Height (mm)'
//                       name='height'
//                       type='number'
//                       value={formData.height}
//                       onChange={handleChange}
//                       required
//                       sx={{
//                         '& .MuiInputLabel-root': {
//                           fontSize: '16px',
//                         },
//                         '& .MuiInputBase-input': {
//                           fontSize: '16px',
//                         },
//                       }}
//                     />
//                   </Grid>
//                   <Grid item xs={6}>
//                     <Button
//                       type='submit'
//                       variant='contained'
//                       color='primary'
//                       startIcon={<StartIcon />}
//                       fullWidth
//                       sx={{
//                         fontSize: '16px',
//                         padding: '8px 16px',
//                       }}>
//                       Start
//                     </Button>
//                   </Grid>
//                   <Grid item xs={6}>
//                     <StopButton robotType='meca' />
//                   </Grid>
//                 </Grid>
//               </form>
//             </CardContent>
//           </Card>
//         </Grid>

//         <Grid item xs={12} md={6}>
//           <LogsPanel />
//         </Grid>
//       </Grid>
//     </Box>
//   );
// }

// export default MecaPickupPage;
