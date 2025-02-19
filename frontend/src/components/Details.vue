<script setup>
import { useRoute, useRouter } from 'vue-router';

const route = useRoute();
const router = useRouter();

const goBack = () => {
  router.push('/');  // Navigate back to root page
};

</script>

<template>
  <div>
    <h2>Detail Page</h2>
    <p>ID: {{ route.params.id }}</p>
    <button @click="goBack">Go Back</button>  <!-- Back button -->
  </div>
</template>