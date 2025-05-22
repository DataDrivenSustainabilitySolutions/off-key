import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Default from "@/pages/Default";
import Login from "@/pages/Login";
import Registration from "@/pages/Registration";
import Verification from "@/pages/Verification";
import "@/App.css";
import { NavigationBar } from "./components/NavigationBar";
import List from "@/pages/List";
import { ThemeProvider } from "./components/theme-provider";

const App: React.FC = () => {
  return (
    <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Default />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Registration />} />
          <Route path="/verify" element={<Verification />} />
          <Route path="/list" element={<List />} />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
};

export default App;
