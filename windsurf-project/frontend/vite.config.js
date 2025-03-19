import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiUrl = mode === 'production' ? env.VITE_PRODUCTION_API_URL : 'http://localhost:8000';

  return {
    define: {
      'process.env.NODE_ENV': JSON.stringify(mode),
      'process.env.REACT_APP_API_URL': JSON.stringify(apiUrl),
    },
    plugins: [react()],
    server: {
      port: 5173,
    }
  };
});