<script setup>
import { ref, onMounted, computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { fetchTelemetryData } from '../services/api'; // Ensure correct path
import {
  Chart as ChartJS,
  Title,
  Tooltip,
  Legend,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  TimeScale
} from 'chart.js';
import { Line } from 'vue-chartjs';
import 'chartjs-adapter-date-fns'; // Needed for time-based x-axis

// Register Chart.js components
ChartJS.register(Title, Tooltip, Legend, LineElement, PointElement, LinearScale, CategoryScale, TimeScale);

const route = useRoute();
const router = useRouter();
const telemetryData = ref([]);
const loading = ref(true);

// Fetch telemetry data on mount
onMounted(async () => {
  const { id, type } = route.params;
  try {
    const response = await fetchTelemetryData(id, type);
    // Sort data in ascending order based on timestamp
    telemetryData.value = response.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
  } catch (error) {
    console.error('Error fetching telemetry data:', error);
  } finally {
    loading.value = false;
  }
});

// Prepare chart data
const chartData = computed(() => ({
  labels: telemetryData.value.map((entry) => new Date(entry.timestamp)), // Convert timestamp to Date object
  datasets: [
    {
      label: `Telemetry Data - ${route.params.type}`,
      data: telemetryData.value.map((entry) => entry.value),
      borderColor: 'rgb(75, 192, 192)',
      backgroundColor: 'rgba(75, 192, 192, 0.2)',
      borderWidth: 2,
      fill: true,
      tension: 0.4, // Smooth curve
    }
  ]
}));

// Chart options
const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  scales: {
    x: {
      type: 'time',
      time: {
        unit: 'second', // Adjust based on granularity
        tooltipFormat: 'yyyy-MM-dd HH:mm:ss',
        displayFormats: {
          second: 'HH:mm:ss',
          minute: 'HH:mm',
          hour: 'HH:mm',
        },
      },
      title: {
        display: true,
        text: 'Time',
      },
    },
    y: {
      title: {
        display: true,
        text: 'Value',
      },
    },
  },
};
</script>

<template>
  <div>
    <h2>Telemetry Detail</h2>
    <p>ID: {{ route.params.id }}</p>
    <p>Type: {{ route.params.type }}</p>
    <button @click="router.back()">Go Back</button>

    <div v-if="loading">Loading telemetry data...</div>
    <div v-else-if="telemetryData.length">
      <div class="chart-container">
        <Line :data="chartData" :options="chartOptions" />
      </div>
    </div>
    <p v-else>No data available.</p>
  </div>
</template>

<style scoped>
.chart-container {
  width: 80vw; /* Set width to 80% of the viewport width */
  max-width: 1000px; /* Prevent it from becoming too large */
  height: 400px; /* Keep the height fixed */
  margin: auto; /* Center it */
}
button {
  margin: 10px 0;
  padding: 10px;
  background: #007bff;
  color: white;
  border: none;
  cursor: pointer;
}
</style>
