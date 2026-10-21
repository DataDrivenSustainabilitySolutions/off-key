import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import {
  AuthLayout,
  AUTH_ERROR_CLASS,
  AUTH_LABEL_CLASS,
  AUTH_LINK_CLASS,
  AUTH_SUCCESS_CLASS,
  AUTH_SUBMIT_BUTTON_CLASS,
} from '@/components/AuthLayout';
import { API_CONFIG, getApiUrl } from '@/lib/api-config';
import { clientLogger } from '@/lib/logger';

const ForgotPassword: React.FC = () => {
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const [failed, setFailed] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return;
    setIsSubmitting(true);
    setMessage('');
    setFailed(false);
    try {
      const res = await fetch(getApiUrl(API_CONFIG.ENDPOINTS.AUTH.FORGOT_PASSWORD), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });

      if (!res.ok) {
        const errorData = await res.json();
        const detail =
          typeof errorData === 'object' &&
          errorData !== null &&
          'detail' in errorData &&
          typeof errorData.detail === 'string'
            ? errorData.detail
            : 'An error occurred while sending the request.';

        clientLogger.error({
          event: 'auth.forgot_password_request_rejected',
          message: 'Forgot password request was rejected',
          error: errorData,
        });

        setMessage(detail);
        setFailed(true);
        return;
      }

      const data = await res.json();
      setMessage(data.message);
    } catch (error) {
      clientLogger.error({
        event: 'auth.forgot_password_request_failed',
        message: 'Forgot password request failed',
        error,
      });
      setMessage('An error occurred while sending the request.');
      setFailed(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthLayout title="Forgot password">
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email Input */}
            <div>
              <Label htmlFor="email" className={AUTH_LABEL_CLASS}>Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="name@company.com"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            {/* Submit Button */}
            <Button
              type="submit"
              className={AUTH_SUBMIT_BUTTON_CLASS}
              disabled={isSubmitting}
              aria-busy={isSubmitting}
            >
              {isSubmitting ? 'Sending…' : 'Reset password'}
            </Button>

            {/* Message */}
            {message && (
              <p role={failed ? 'alert' : 'status'} className={`mt-2 text-center text-sm ${failed ? AUTH_ERROR_CLASS : AUTH_SUCCESS_CLASS}`}>
                {message}
              </p>
            )}

            <p className="text-center text-sm">
              <Link to="/login" className={AUTH_LINK_CLASS}>Back to log in</Link>
            </p>
          </form>
    </AuthLayout>
  );
};

export default ForgotPassword;
