import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import Login from './Login';
import Registration from './Registration';

const Default: React.FC = () => {
  return (
    <Router>
      <div className="min-h-screen flex flex-col">
        {/* Navigation Bar */}
        <nav className="flex justify-between items-center p-6 bg-gray-800 text-white">
          <div className="text-2xl font-bold">
            <Link to="/">Off-Key</Link>
          </div>
          <div className="space-x-4">
            <Link to="/login">
              <Button variant="outline" className="text-white border-white">
                Login
              </Button>
            </Link>
            <Link to="/register">
              <Button variant="solid" className="bg-white text-gray-800">
                Register
              </Button>
            </Link>
          </div>
        </nav>
        {/* Main Content */}
        <main className="flex-grow flex items-center justify-center bg-gray-100">
          <Routes>
            <Route
              path="/"
              element={
                <div className="text-center p-6">
                  <h1 className="text-5xl font-extrabold mb-4">Welcome to Off-Key</h1>
                  <p className="text-xl text-gray-700">
                    Discover the unique features of our project and join our community today.
                  </p>
                </div>
              }
            />
            <Route path="/login" element={<Login />} />
            <Route path="/registration" element={<Registration />} />
          </Routes>
        </main>
        {/* Footer */}
        <footer className="p-4 bg-gray-800 text-white text-center">
          &copy; {new Date().getFullYear()} Off-Key. All rights reserved.
        </footer>
      </div>
    </Router>
  );
};

export default App;
