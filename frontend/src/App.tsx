import { Suspense } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { Toaster } from "react-hot-toast";

import "@/App.css";
import { AuthProvider } from "@/auth/AuthContext";
import { FullPageLoading } from "@/components/LoadingStates";
import { ThemeProvider } from "@/components/theme-provider";
import { createAppRoutes } from "@/routes";

const router = createBrowserRouter(createAppRoutes());

const App = () => (
  <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
    <AuthProvider>
      <Suspense fallback={<FullPageLoading message="Loading page..." />}>
        <RouterProvider router={router} />
      </Suspense>
    </AuthProvider>
    <Toaster
      position="top-right"
      toastOptions={{
        style: {
          color: "hsl(var(--foreground))",
          background: "hsl(var(--popover))",
          border: "1px solid hsl(var(--border))",
          borderRadius: "12px",
          boxShadow: "0 16px 40px hsl(220 20% 10% / 0.12)",
          fontSize: "14px",
        },
      }}
    />
  </ThemeProvider>
);

export default App;
