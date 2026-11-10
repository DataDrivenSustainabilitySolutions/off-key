import { Suspense } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { Toaster } from "react-hot-toast";

import "@/App.css";
import { AuthProvider } from "@/auth/AuthContext";
import { FullPageLoading } from "@/components/LoadingStates";
import { ThemeProvider } from "@/components/theme-provider";
import { useToastPosition } from "@/hooks/use-toast-position";
import { createAppRoutes } from "./routes";

const router = createBrowserRouter(createAppRoutes());

const App = () => (
  <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
    <AuthProvider>
      <Suspense fallback={<FullPageLoading message="Loading page..." />}>
        <RouterProvider router={router} />
      </Suspense>
    </AuthProvider>
    <AppToaster />
  </ThemeProvider>
);

/** Toasts appear top right, unless the page shown asks for another place. */
function AppToaster() {
  return (
    <Toaster
      position={useToastPosition()}
      toastOptions={{
        style: {
          color: "hsl(var(--foreground))",
          background: "hsl(var(--popover))",
          border: "1px solid hsl(var(--border))",
          borderRadius: "12px",
          boxShadow: "0 16px 40px hsl(220 20% 10% / 0.12)",
          fontSize: "var(--text-body)",
        },
      }}
    />
  );
}

export default App;
