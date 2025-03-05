import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Default from './components/Default'
import Login from './components/Login';
import Registration from './components/Registration';
import Verification from './components/Verification';
import './App.css';

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Default />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Registration />} />
        <Route path="/verify" element={<Verification />} />
        {/* Add other routes (e.g. Registration, Protected Dashboard, etc.) */}
      </Routes>
    </BrowserRouter>
  );
};

export default App;
