<script setup>
import { ref, onMounted } from 'vue';
import {fetchActiveChargerIDs} from '@/services/api';

const activeChargerIDs = ref(null); // Declare a reactive reference to store the fetched data

onMounted(() => {
  fetchActiveChargerIDs()  // Call the fetchData function
    .then(responseData => {
      activeChargerIDs.value = responseData;  // Set the response data to the data ref
    })
    .catch(error => {
      console.error('Failed to fetch data:', error);
    });
});

</script>

<template>
  <div>
    <h1>Data from API</h1>
    <pre>{{ activeChargerIDs }}</pre>  <!-- Display the fetched data -->
  </div>
</template>

<style scoped>
.read-the-docs {
  color: #888;
}
</style>
