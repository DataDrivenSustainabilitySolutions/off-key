<script setup>
import { ref, onMounted } from 'vue';
import { fetchData } from '@/services/api';  // Adjust the path as necessary

const data = ref(null); // Declare a reactive reference to store the fetched data

onMounted(() => {
  fetchData()  // Call the fetchData function
    .then(responseData => {
      data.value = responseData;  // Set the response data to the data ref
    })
    .catch(error => {
      console.error('Failed to fetch data:', error);
    });
});
</script>

<template>
  <div>
    <h1>Data from API</h1>
    <pre>{{ data }}</pre>  <!-- Display the fetched data -->
  </div>
</template>

<style scoped>
.read-the-docs {
  color: #888;
}
</style>
