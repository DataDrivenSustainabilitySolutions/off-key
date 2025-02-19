<script setup>
import { ref, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { fetchAvailableTelemetryTypes } from '../services/api'; // Adjust the import path as necessary

const route = useRoute();
const router = useRouter();

const telemetryTypes = ref([]); // Reactive reference to store telemetry types

const goBack = () => {
  router.push('/');  // Navigate back to root page
};

const goToTelemetryDetail = (type) => {
  const chargerId = route.params.id; // Get the charger ID from route params
  router.push(`/chargers/${chargerId}/telemetry/${type}`); // Navigate to the telemetry detail page with charger ID
};

// Fetch telemetry types when the component is mounted
onMounted(async () => {
  const chargerId = route.params.id; // Get the charger ID from route params
  try {
    const response = await fetchAvailableTelemetryTypes(chargerId); // Fetch telemetry types using the charger ID
    telemetryTypes.value = response; // Assuming response is an array of types
  } catch (error) {
    console.error('Error fetching telemetry types:', error);
  }
});

</script>

<template>
  <div>
    <h2>Detail Page</h2>
    <p>ID: {{ route.params.id }}</p>
    <button @click="goBack">Go Back</button>  <!-- Back button -->

    <h3>Available Telemetry Types</h3>
    <div v-if="telemetryTypes.length">
      <button v-for="type in telemetryTypes" :key="type" @click="goToTelemetryDetail(type)">
        {{ type }}
      </button>
    </div>
    <p v-else>Loading telemetry types...</p>
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