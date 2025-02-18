import axios from 'axios';

// Assuming the API URL is set in the environment variable
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL, // Now this is http://localhost:8000
});

export const fetchData = async () => {
  try {
    const response = await api.get('/data');
    return response.data;  // Returns the data from the API
  } catch (error) {
    console.error('Error fetching data:', error);
    throw error;
  }
};
