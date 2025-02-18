import axios from 'axios';

const apiUrl = import.meta.env.API_URL;

export const fetchData = () => {
  return axios.get(`${apiUrl}/some-endpoint`)
    .then(response => response.data)
    .catch(error => {
      console.error(error);
      throw error;  // Rethrow or handle error
    });
};