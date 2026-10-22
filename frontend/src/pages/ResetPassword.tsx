import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import {
  AuthLayout,
  AUTH_ERROR_CLASS,
  AUTH_SUCCESS_CLASS,

  AUTH_LABEL_CLASS,
  AUTH_LINK_CLASS,
  AUTH_SUBMIT_BUTTON_CLASS,
} from '@/components/AuthLayout';
import { API_CONFIG, getApiUrl } from "@/lib/api-config";
import { clientLogger } from "@/lib/logger";
import { validatePassword, validatePasswordConfirmation } from "@/lib/validation";

const ResetPassword: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const token = new URLSearchParams(location.hash.slice(1)).get('token');
  const [newPassword, setNewPassword] = useState('');
  const [confirmNewPassword, setConfirmNewPassword] = useState('');
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return;
    setMessage('');
    setError('');

    if (!token) {
      setError('Token is missing.');
      return;
    }

    const validation = [validatePassword(newPassword), validatePasswordConfirmation(newPassword, confirmNewPassword)].find((result) => !result.isValid);
    if (validation) {
      setError(validation.message ?? 'Check your password.');
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await fetch(getApiUrl(API_CONFIG.ENDPOINTS.AUTH.RESET_PASSWORD), {
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
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthLayout title="Reset password">
          {!token && (
            <div className="space-y-4 text-center text-sm">
              <p role="alert" className={AUTH_ERROR_CLASS}>This reset link is incomplete. Open the link from your email again, or request a new one.</p>
              <Link to="/forgot-password" className={AUTH_LINK_CLASS}>Request a new link</Link>
            </div>
          )}
          {token && error && (
            <p role="alert" className={`mb-4 text-center text-sm ${AUTH_ERROR_CLASS}`}>{error}</p>
          )}
          {message && (
            <p role="status" className={`mb-4 text-center text-sm ${AUTH_SUCCESS_CLASS}`}>{message}</p>
          )}
          {token && !message && (
            <form onSubmit={handleSubmit} className="space-y-4">
              {/* New password */}
              <div>
                <Label htmlFor="newPassword" className={AUTH_LABEL_CLASS}>
                  New password
                </Label>
                <Input
                  id="newPassword"
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  minLength={12}
                  autoComplete="new-password"
                  aria-describedby="newPasswordHint"
                />
                <p id="newPasswordHint" className="mt-1.5 text-xs text-muted-foreground">Use at least 12 characters.</p>
              </div>
              <div>
                <Label htmlFor="confirmNewPassword" className={AUTH_LABEL_CLASS}>
                  Confirm password
                </Label>
                <Input
                  id="confirmNewPassword"
                  type="password"
                  value={confirmNewPassword}
                  onChange={(e) => setConfirmNewPassword(e.target.value)}
                  required
                  minLength={12}
                  autoComplete="new-password"
                />
              </div>

              {/* Reset Button */}
              <Button
                type="submit"
                className={AUTH_SUBMIT_BUTTON_CLASS}
                disabled={isSubmitting}
                aria-busy={isSubmitting}
              >
                {isSubmitting ? 'Resetting…' : 'Reset password'}
              </Button>
            </form>
          )}
    </AuthLayout>
  );
};

export default ResetPassword;
