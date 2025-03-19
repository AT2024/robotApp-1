import axios from 'axios';
import { API_URL } from './config';

const api = axios.create({
    baseURL: API_URL,
});

export const createPickup = (data) => api.post('/api/meca/pickup', data);
export const createDrop = (data) => api.post('/api/meca/drop', data);
export const getPickups = () => api.get('/api/meca/pickups');
export const getDrops = () => api.get('/api/meca/drops');
export const updatePickup = (id, data) => api.put(`/api/meca/pickup/${id}`, data);
export const updateDrop = (id, data) => api.put(`/api/meca/drop/${id}`, data);
export const deletePickup = (id) => api.delete(`/api/meca/pickup/${id}`);
export const deleteDrop = (id) => api.delete(`/api/meca/drop/${id}`);

export default api;