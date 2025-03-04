import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Login from './components/Login'; // Import your Login component (make sure this path is correct)
import './App.css'; // Import your CSS file

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<div>Welcome to the Home Page!</div>} /> {/* Default route */}
        <Route path="/login" element={<Login />} />
        {/* Add other routes (e.g. Registration, Protected Dashboard, etc.) */}
      </Routes>
    </BrowserRouter>
  );
};

export default App;
