import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
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
    <div className="min-h-screen flex items-center justify-center bg-gray-100 px-4">
      <Card className="w-full max-w-md p-6">
        <CardHeader>
          <CardTitle className="text-center text-2xl">Forgot password</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email Input */}
            <div>
              <Label htmlFor="email" className="mb-1 block text-sm">E-Mail</Label>
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
              className="w-full bg-gradient-to-r from-slate-400 to-slate-300 text-white font-semibold rounded-full transition-all duration-200 hover:bg-gradient-to-r hover:from-slate-500 hover:to-slate-400 hover:scale-105 cursor-pointer"
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
        </CardContent>
      </Card>
    </div>
  );
};

export default ForgotPassword;
