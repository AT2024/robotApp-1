// import React, { useState } from 'react';
// import {
//   Box,
//   Card,
//   CardContent,
//   Typography,
//   TextField,
//   Button,
//   Grid,
//   FormControl,
//   InputLabel,
//   Select,
//   MenuItem,
// } from '@mui/material';
// import { PlayArrow as StartIcon } from '@mui/icons-material';
// import { ToastContainer, toast } from 'react-toastify';
// import 'react-toastify/dist/ReactToastify.css';
// import StopButton from '../components/StopButton';
// import LogsPanel from '../components/LogsPanel';
// import api from '../services/api';

// function OT2ProtocolPage() {
//   const [formData, setFormData] = useState({
//     protocolName: '',
//     plateType: 'plate_96',
//     wellStart: '',
//     wellEnd: '',
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
//       await api.post('/api/ot2/protocol', formData);
//       toast.success('Protocol started successfully');
//     } catch (error) {
//       toast.error(`Error starting protocol: ${error.message}`);
//     }
//   };

//   return (
//     <Box
//       sx={{
//         '& .MuiGrid-container': {
//           spacing: 3,
//         },
//         '& .MuiGrid-item': {
//           xs: 12,
//           md: 6,
//         },
//         '& .MuiCard': {
//           maxWidth: '100%',
//         },
//         '& .MuiCardContent': {
//           padding: 2,
//         },
//         '& .MuiTypography-h4': {
//           marginBottom: 2,
//         },
//         '& .MuiGrid-container form': {
//           display: 'flex',
//           flexDirection: 'column',
//           alignItems: 'center',
//           padding: 2,
//         },
//         '& .MuiGrid-item .MuiFormControl-fullWidth': {
//           marginBottom: 2,
//         },
//         '& .MuiGrid-item .MuiButton-fullWidth': {
//           marginBottom: 2,
//         },
//       }}>
//       <Typography variant='h4' gutterBottom>
//         OT2 Protocol Control
//       </Typography>

//       <Grid container spacing={3}>
//         <Grid item xs={12} md={6}>
//           <Card>
//             <CardContent>
//               <form onSubmit={handleSubmit}>
//                 <Grid container spacing={2}>
//                   <Grid item xs={12}>
//                     <TextField
//                       fullWidth
//                       label='Protocol Name'
//                       name='protocolName'
//                       value={formData.protocolName}
//                       onChange={handleChange}
//                       required
//                     />
//                   </Grid>
//                   <Grid item xs={12}>
//                     <FormControl fullWidth>
//                       <InputLabel>Plate Type</InputLabel>
//                       <Select
//                         name='plateType'
//                         value={formData.plateType}
//                         onChange={handleChange}
//                         label='Plate Type'>
//                         <MenuItem value='plate_96'>96 Well Plate</MenuItem>
//                         <MenuItem value='plate_384'>384 Well Plate</MenuItem>
//                       </Select>
//                     </FormControl>
//                   </Grid>
//                   <Grid item xs={6}>
//                     <TextField
//                       fullWidth
//                       label='Start Well'
//                       name='wellStart'
//                       value={formData.wellStart}
//                       onChange={handleChange}
//                       required
//                     />
//                   </Grid>
//                   <Grid item xs={6}>
//                     <TextField
//                       fullWidth
//                       label='End Well'
//                       name='wellEnd'
//                       value={formData.wellEnd}
//                       onChange={handleChange}
//                       required
//                     />
//                   </Grid>
//                   <Grid item xs={6}>
//                     <Button
//                       type='submit'
//                       variant='contained'
//                       color='primary'
//                       startIcon={<StartIcon />}
//                       fullWidth>
//                       Start Protocol
//                     </Button>
//                   </Grid>
//                   <Grid item xs={6}>
//                     <StopButton robotType='ot2' />
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

// export default OT2ProtocolPage;
