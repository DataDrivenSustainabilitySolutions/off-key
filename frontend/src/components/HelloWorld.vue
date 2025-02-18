<script setup>
import { ref } from 'vue'

defineProps({
  msg: String,
})

const count = ref(0)
</script>

<template>
  <div>
    <h1>Data from API</h1>
    <pre>{{ data }}</pre>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { fetchData } from '@/services/api';  // Adjust the path as necessary

const data = ref(null);

onMounted(() => {
  fetchData()
    .then(responseData => {
      data.value = responseData;
    })
    .catch(error => {
      console.error(error);
    });
});
</script>

<style scoped>
.read-the-docs {
  color: #888;
}
</style>
