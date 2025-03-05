import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Default from './components/Default.tsx'
import Login from './components/Login.tsx';
import Registration from './components/Registration.tsx';
import Verification from './components/Verification.tsx';
import './App.css';

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Default />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Registration />} />
        <Route path="/verify" element={<Verification />} />
      </Routes>
    </BrowserRouter>
  );
};

export default App;
