import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

const ResetPassword: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const [token, setToken] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [confirmNewPassword, setConfirmNewPassword] = useState('');
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');

  useEffect(() => {
    const t = searchParams.get('token');
    if (t) {
      setToken(t);
    } else {
      setError('No token found');
    }
  }, [searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage('');
    setError('');

    if (!token) {
      setError('Token is missing.');
      return;
    }

    if (newPassword.length < 8) {
      setError('The password must be at least 8 characters long.');
      return;
    }

    try {
      const response = await fetch('/api/v1/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: newPassword }),
      });

      if (!response.ok) {
        const data = await response.json();
        setError(data.detail || 'Error while resetting the password.');
        return;
      }

      setMessage('Password successfully reset. You will be redirected...');
      setTimeout(() => navigate('/login'), 3000); // Navigate to login page after 3 seconds
    } catch (err) {
      setError('Server error. Please try again later.');
      console.error(err);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100 px-4">
      <Card className="w-full max-w-md p-6">
        <CardHeader>
          <CardTitle className="text-center text-2xl">Reset password</CardTitle>
        </CardHeader>
        <CardContent>
          {error && (
            <p className="mb-4 text-center text-sm text-red-600">{error}</p>
          )}
          {message && (
            <p className="mb-4 text-center text-sm text-green-600">{message}</p>
          )}
          {!message && (
            <form onSubmit={handleSubmit} className="space-y-4">
              {/* Neues Passwort */}
              <div>
                <Label htmlFor="newPassword" className="mb-1 block text-sm">
                  New passwort
                </Label>
                <Input
                  id="newPassword"
                  type="password"
                  placeholder="Neues Passwort"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  minLength={8}
                />
              </div>
              <div>
                <Label htmlFor="confirmNewPassword" className="mb-1 block text-sm">
                  Confirm password
                </Label>
                <Input
                  id="confirmNewPassword"
                  type="password"
                  placeholder="Password bestätigen"
                  value={confirmNewPassword}
                  onChange={(e) => setConfirmNewPassword(e.target.value)}
                  required
                  minLength={8}
                />
              </div>

              {/* Reset Button */}
              <Button
                type="submit"
                className="w-full bg-gradient-to-r from-slate-400 to-slate-300 text-white font-semibold rounded-full transition-all duration-200 hover:bg-gradient-to-r hover:from-slate-500 hover:to-slate-400 hover:scale-105 cursor-pointer"
              >
                Reset password
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default ResetPassword;
