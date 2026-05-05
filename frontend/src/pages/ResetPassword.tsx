import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import {
  AuthLayout,
  AUTH_LABEL_CLASS,
  AUTH_SUBMIT_BUTTON_CLASS,
} from '@/components/AuthLayout';
import { clientLogger } from "@/lib/logger";

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
      clientLogger.error({
        event: "auth.reset_password_request_failed",
        message: "Reset password request failed",
        error: err,
      });
    }
  };

  return (
    <AuthLayout title="Reset password">
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
                <Label htmlFor="newPassword" className={AUTH_LABEL_CLASS}>
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
                <Label htmlFor="confirmNewPassword" className={AUTH_LABEL_CLASS}>
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
                className={AUTH_SUBMIT_BUTTON_CLASS}
              >
                Reset password
              </Button>
            </form>
          )}
    </AuthLayout>
  );
};

export default ResetPassword;
