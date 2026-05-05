import React, { useState } from 'react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import {
  AuthLayout,
  AUTH_LABEL_CLASS,
  AUTH_SUBMIT_BUTTON_CLASS,
} from '@/components/AuthLayout';
import { API_CONFIG, getApiUrl } from '@/lib/api-config';
import { clientLogger } from '@/lib/logger';

const ForgotPassword: React.FC = () => {
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
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
    }
  };

  return (
    <AuthLayout title="Forgot password">
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email Input */}
            <div>
              <Label htmlFor="email" className={AUTH_LABEL_CLASS}>E-Mail</Label>
              <Input
                id="email"
                type="email"
                placeholder="Your E-Mail"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            {/* Submit Button */}
            <Button
              type="submit"
              className={AUTH_SUBMIT_BUTTON_CLASS}
            >
              Reset Password
            </Button>

            {/* Message */}
            {message && (
              <p className={`mt-2 text-center text-sm `}>
                {message}
              </p>
            )}
          </form>
    </AuthLayout>
  );
};

export default ForgotPassword;
