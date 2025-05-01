import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Default from "@/pages/Default";
// import Login from '@/pages/Login';
// import Registration from '@/pages/Registration';
// import Verification from '@/pages/Verification';
import "@/App.css";
// import {NavigationBar} from "./components/NavigationBar";

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Default />} />
        {/* <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Registration />} />
        <Route path="/verify" element={<Verification />} /> */}
      </Routes>
    </BrowserRouter>
  );
};

export default App;
