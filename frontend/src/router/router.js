import { createRouter, createWebHistory } from 'vue-router';
import LandingPage from "../components/LandingPage.vue";
import Details from "../components/Details.vue";
import LineChart from "../components/LineChart.vue";

const routes = [
    { path: '/', component: LandingPage },
    { path: '/details/:id', component: Details },
    { path: '/chargers/:id/telemetry/:type', component: LineChart}
];

const router = createRouter({
    history: createWebHistory(),
    routes
});

export default router;