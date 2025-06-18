import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { useNavigate } from 'react-router-dom';
import { Link } from 'react-router-dom';
import { useAuth } from "@/auth/AuthContext";

interface LoginResponse {
  access_token: string;
  token_type: string;
}

const Login: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword] = useState(false);
  const [message, setMessage] = useState('');
  const navigate = useNavigate();
  const { login } = useAuth();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        setMessage(errorData.detail || 'Login fehlgeschlagen');
        return;
      }

      const data: LoginResponse = await response.json();
      login(data.access_token);
      setMessage('Login erfolgreich!');
      setTimeout(() => {
        navigate('/');
      }, 2000);
    } catch (error) {
      console.error(error);
      setMessage('Es ist ein Fehler aufgetreten.');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100 px-4">
      <Card className="w-full max-w-md p-6">
        <CardHeader>
          <CardTitle className="text-center text-2xl">Login</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            {/* E-Mail */}
            <div>
              <Label htmlFor="email" className="mb-1 block text-sm">E-Mail</Label>
              <Input
                id="email"
                type="email"
                placeholder="E-Mail"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="relative">
              <Label htmlFor="password" className="mb-1 block text-sm">Passwort</Label>
              <Input
                id="password"
                type={showPassword ? 'text' : 'password'}
                placeholder="Passwort"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              {/* <button
                type="button"
                className="absolute right-3 top-9 text-gray-500"
                onClick={() => setShowPassword(!showPassword)}
                aria-label="Passwort anzeigen"
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button> */}
            </div>

            <div className="flex items-center space-x-2 text-sm">
              <input type="checkbox" id="remember" className="accent-green-600" />
              <label htmlFor="remember">Angemeldet bleiben</label>
            </div>

            {/* Login Button */}
            <Button
              type="submit"
              className="w-full bg-gradient-to-r from-slate-400 to-slate-300 text-white font-semibold rounded-full transition-all duration-200 hover:bg-gradient-to-r hover:from-slate-500 hover:to-slate-400 hover:scale-105 cursor-pointer"
            >
              EINLOGGEN
            </Button>

            {/* Fehlermeldung oder Erfolgsnachricht */}
            {message && (
              <p className={`mt-2 text-center text-sm ${message === 'Login erfolgreich!' ? 'text-green-600' : 'text-red-600'}`}>
                {message}
              </p>
            )}

            {/* Links */}
            <div className="text-sm text-center mt-3 space-y-1">
              <Link to="/forgot-password" className="text-blue-700 hover:underline block">
                Forgot password?
              </Link>
            </div>
            <div className="text-xs mt-4 text-center">
              <p>
                Not signed up yet?{' '}
                <Link to="/register" className="text-blue-600 hover:underline">
                  Register here
                </Link>
              </p>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};

export default Login;
