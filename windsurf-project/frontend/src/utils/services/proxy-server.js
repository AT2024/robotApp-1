// proxy-server.js
const express = require('express');
const cors = require('cors');
const axios = require('axios');
const app = express();

// Enable CORS for your frontend
app.use(
  cors({
    origin: 'http://localhost:5173', // Your Vite frontend URL
    methods: ['GET', 'POST', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization'],
  })
);

app.use(express.json());

// Create proxy endpoint for OCR
app.post('/api/ocr/extract', async (req, res) => {
  try {
    const response = await axios({
      method: 'post',
      url: 'https://ocrserver.docsumo.com/api/v1/ocr/extract/',
      data: req.body,
      headers: {
        'Content-Type': 'application/json',
        // Add any required API keys here
      },
    });

    res.json(response.data);
  } catch (error) {
    console.error('Proxy error:', error.message);
    res.status(500).json({
      error: 'Failed to process OCR request',
      details: error.message,
    });
  }
});

const PORT = 3000;
app.listen(PORT, () => {
  console.log(`Proxy server running on http://localhost:${PORT}`);
});
