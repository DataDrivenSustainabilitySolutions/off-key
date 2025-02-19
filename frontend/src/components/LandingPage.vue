<script setup>
import { ref, onMounted } from 'vue';
import {fetchActiveChargerIDs} from '../services/api';
import { useRouter } from 'vue-router';

const activeChargerIDs = ref([]); // Declare a reactive reference to store the fetched data
const router = useRouter();

onMounted(async () => {
  try {
    const response = await fetchActiveChargerIDs(); // Replace with your API
    activeChargerIDs.value = response.active;
  } catch (error) {
    console.error('Error fetching data:', error);
  }
});

const goToDetail = (id) => {
  router.push(`/details/${id}`);
};

</script>

<template>
  <div>
    <h2>Active Items</h2>
    <div v-if="activeChargerIDs.length">
      <button v-for="id in activeChargerIDs" :key="id" @click="goToDetail(id)">
        {{ id }}
      </button>
    </div>
    <p v-else>No telemetry information available.</p>
  </div>
</template>

<style scoped>
.read-the-docs {
  color: #888;
}
button {
  display: block;
  margin: 5px 0;
  padding: 10px;
  background: #007bff;
  color: white;
  border: none;
  cursor: pointer;
}
</style>
