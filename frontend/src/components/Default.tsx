import React from 'react';
import { Routes, Route, Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import Login from '@/components/Login.tsx';
import Registration from '@/components/Registration.tsx';

const Default: React.FC = () => {
  return (
    <div className="min-h-screen flex flex-col bg-white text-gray-900">
      {/* Navigation Bar */}
      <nav className="flex justify-between items-center p-6 max-w-7xl mx-auto w-full">
        <div className="text-2xl font-bold">
          <Link to="/" className="hover:text-gray-700 transition-colors">
            off-key
          </Link>
        </div>
        <div className="space-x-4">
          <Link to="/login">
            <Button variant="ghost" className="text-gray-900 hover:bg-gray-100">
              Login
            </Button>
          </Link>
          <Link to="/register">
            <Button className="bg-gray-900 text-white hover:bg-gray-800">
              Register
            </Button>
          </Link>
        </div>
      </nav>

      {/* Main Content */}
      <main className="flex-grow flex items-center justify-center">
        <Routes>
          <Route
            path="/"
            element={
              <div className="text-center p-6 max-w-2xl">
                <h1 className="text-5xl font-extrabold mb-6">
                  Welcome to{" "}
                  <span className="bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                    off-key
                  </span>
                </h1>
                <p className="text-xl text-gray-600 mb-8">
                  Discover the unique features of our project and join our community today. Let’s create something amazing together.
                </p>
                <div className="space-x-4">
                  <Link to="/login">
                    <Button variant="outline" className="border-gray-900 text-gray-900 hover:bg-gray-100">
                      Get Started
                    </Button>
                  </Link>
                  <Link to="/register">
                    <Button className="bg-gray-900 text-white hover:bg-gray-800">
                      Join Now
                    </Button>
                  </Link>
                </div>
              </div>
            }
          />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Registration />} />
        </Routes>
      </main>

      {/* Footer */}
      <footer className="p-6 bg-gray-50 text-center text-gray-600 text-xs">
        <p>&copy; {new Date().getFullYear()} off-key. All rights reserved.</p>
      </footer>
    </div>
  );
};

export default Default;
