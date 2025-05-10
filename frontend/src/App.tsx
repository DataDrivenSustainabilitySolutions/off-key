import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
// import Default from "@/pages/Default";
// import Login from '@/pages/Login';
// import Registration from '@/pages/Registration';
// import Verification from '@/pages/Verification';
import "@/App.css";
import Details from "./pages/Details";
import { NavigationBar } from "./components/NavigationBar";

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <NavigationBar />
      <Routes>
        <Route path="/" element={<Details />} />
        {/* <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Registration />} />
        <Route path="/verify" element={<Verification />} /> */}
      </Routes>
    </BrowserRouter>
  );
};

export default App;
