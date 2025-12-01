import React from 'react';
import { BrowserRouter as Router, Route, Routes, Navigate } from 'react-router-dom';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import CarouselAssemblyStatusPage from "./pages/CarouselAssemblyStatusPage";
import SpreadingPage from './pages/spreading_page';
import WelcomePage from './WelcomePage';
import Layout from './pages/Layout';
import ConfigPage from './pages/ConfigPage';
import SpreadingFormPage from './pages/spreading_form_page';
import CarouselAssemblyPage from './pages/Carousel_assembly_page';



// AppRoutes component to separate routing logic
const AppRoutes = () => (
  <Routes>
    {/* Public routes */}
    <Route
      path='/welcome'
      element={
        <div className='min-h-screen bg-gray-50'>
          <WelcomePage />
        </div>
      }
    />

    {/* Protected routes wrapped in Layout */}
    <Route
      path='/spreading/form'
      element={
        <Layout>
          <SpreadingFormPage />
        </Layout>
      }
    />

    <Route
      path='/spreading'
      element={
        <Layout>
          <SpreadingPage />
        </Layout>
      }
    />

    <Route
      path='/Carousel-assembly'
      element={
        <Layout>
          <CarouselAssemblyPage />
        </Layout>
      }
    />

    <Route
      path='/config/:type'
      element={
        <Layout>
          <ConfigPage />
        </Layout>
      }
    />
    <Route
      path='/carousel-assembly-status'
      element={
        <Layout>
          <CarouselAssemblyStatusPage />
        </Layout>
      }
    />

    {/* Default redirect */}
    <Route path='/' element={<Navigate to='/welcome' replace />} />
  </Routes>
);

// Main App component
const App = () => (
  <Router>
    <div className='min-h-screen bg-gray-50 text-gray-900 font-sans antialiased'>
      <AppRoutes />
      <ToastContainer
        position="top-center"
        autoClose={3000}
        hideProgressBar={false}
        newestOnTop
        closeOnClick
        rtl={false}
        pauseOnFocusLoss
        draggable
        pauseOnHover
        theme="light"
      />
    </div>
  </Router>
);

export default App;
