import React, { useState } from 'react';
import {
  Box,
  AppBar,
  Toolbar,
  Typography,
  Drawer,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import {
  Science as ScienceIcon,
  Settings as SettingsIcon,
  ArrowUpward as PickupIcon,
  ArrowDownward as DropIcon,
  Memory as ArduinoIcon,
} from '@mui/icons-material';
import { Link } from 'react-router-dom';

const drawerWidth = 240;

const menuItems = [
  { text: 'Radioactive on wafer', icon: <PickupIcon />, path: '/spreading/form' },
  { text: 'Carousel Assembly', icon: <PickupIcon />, path: '/Carousel-assembly' },
  { text: 'rebuilt Carousel', icon: <ArduinoIcon />, path: '/arduino/steps' },
  { text: 'Meca Configuration', icon: <SettingsIcon />, path: '/config/meca' },
  { text: 'OT2 Configuration', icon: <SettingsIcon />, path: '/config/ot2' },
];

const Layout = ({ children }) => {
  const navigate = useNavigate();
  const [configContent, setConfigContent] = useState('');



  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar position='fixed'>
        <Toolbar>
          <Typography variant='h6' noWrap component='div'>
            Robotic Control Panel
          </Typography>
        </Toolbar>
      </AppBar>
      <Drawer
        sx={{
          width: drawerWidth,
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: drawerWidth,
            boxSizing: 'border-box',
          },
        }}
        variant='permanent'
        anchor='left'>
        <List>
          {menuItems.map((item, index) => (
            <ListItem button key={index} onClick={() => navigate(item.path)}>
              <ListItemIcon>{item.icon}</ListItemIcon>
              <ListItemText primary={item.text} />
            </ListItem>
          ))}
        </List>
      </Drawer>
      <Box component='main' sx={{ flexGrow: 1, bgcolor: 'background.default', p: 3 }}>
        <Toolbar />
        {children}
        {configContent && <pre>{configContent}</pre>} {/* Display the config content */}
      </Box>
    </Box>
  );
};

export default Layout;