import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

interface RegistrationResponse {
  message: string;
}

const Registration: React.FC = () => {
  const [email, setEmail] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [confirmPassword, setConfirmPassword] = useState<string>('');
  const [message, setMessage] = useState<string>('');

  const handleRegister = async (e: React.FormEvent) => {
  e.preventDefault();

  if (password !== confirmPassword) {
    setMessage('Passwords do not match.');
    return;
  }

  if (password.length < 8) {
    setMessage('Password should be at least 8 characters long.');
    return;
  }

  try {
    const response = await fetch('http://localhost:8000/v1/auth/register', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password, role: "user"}),
    });
    if (!response.ok) {
      const errorData = await response.json();
      setMessage(errorData.detail || 'Registration failed');
      return;
    }

    const data: RegistrationResponse = await response.json();
    setMessage(data.message || 'Registration successful! Please check your email to verify your account.');

    // Redirect after successful registration (optional)
    setTimeout(() => {
      window.location.href = '/login'; // Redirect to login page
    }, 3000);
  } catch (error) {
    console.error(error);
    setMessage('An error occurred.');
  }
};


  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-center">Register</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleRegister} className="space-y-4">
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
            <div>
              <Label htmlFor="confirmPassword" className="block mb-1">
                Confirm Password
              </Label>
              <Input
                id="confirmPassword"
                type="password"
                placeholder="Confirm your password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
            </div>
            <Button type="submit" className="w-full">
              Register
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

export default Registration;
