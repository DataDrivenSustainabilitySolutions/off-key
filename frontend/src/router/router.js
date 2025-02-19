import { createRouter, createWebHistory } from 'vue-router';
import HelloWorld from "../components/HelloWorld.vue";
import Details from "../components/Details.vue";

const routes = [
    { path: '/', component: HelloWorld },
    { path: '/details/:id', component: Details }
];

const router = createRouter({
    history: createWebHistory(),
    routes
});

export default router;