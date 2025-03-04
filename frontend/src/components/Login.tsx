import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

interface LoginResponse {
  access_token: string;
  token_type: string;
}

const Login: React.FC = () => {
  const [email, setEmail] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [message, setMessage] = useState<string>('');

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const formData = new URLSearchParams();
      // OAuth2PasswordRequestForm expects "username" and "password"
      formData.append('username', email);
      formData.append('password', password);
      const response = await fetch('http://localhost:8000/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData.toString(),
      });
      if (!response.ok) {
        const errorData = await response.json();
        setMessage(errorData.detail || 'Login failed');
        return;
      }
      const data: LoginResponse = await response.json();
      // Store token in localStorage
      localStorage.setItem('token', data.access_token);
      setMessage('Login successful!');
      // Redirect or update UI as needed...
    } catch (error) {
      console.error(error);
      setMessage('An error occurred.');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-center">Login</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <Label htmlFor="email" className="block mb-1">
                Email
              </Label>
              <Input
                id="email"
                type="email"
                placeholder="Enter your email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <Label htmlFor="password" className="block mb-1">
                Password
              </Label>
              <Input
                id="password"
                type="password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <Button type="submit" className="w-full">
              Login
            </Button>
          </form>
          {message && (
            <p className="mt-4 text-center text-green-600">
              {message}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default Login;
