import axios from 'axios';

const handleDismantle = async (trayNumber) => {
  try {
    const startIndex = parseInt(trayNumber, 10);
    await axios.post('/api/meca/dismantle', { start: startIndex, count: 5 });
    alert('Dismantling process started.');
  } catch (error) {
    alert('Error starting dismantling process.');
    console.error(error);
  }
};

export default handleDismantle;
