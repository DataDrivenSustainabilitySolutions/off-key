import React, { useState } from 'react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Link } from 'react-router-dom';
import { Eye, EyeOff } from 'lucide-react';
import {
  AuthLayout,
  AUTH_LABEL_CLASS,
  AUTH_SUBMIT_BUTTON_CLASS,
} from '@/components/AuthLayout';
import { clientLogger } from "@/lib/logger";

interface RegistrationResponse {
  message: string;
}

const Registration: React.FC = () => {
  const [email, setEmail] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [confirmPassword, setConfirmPassword] = useState<string>('');
  const [message, setMessage] = useState<string>('');
  const [isError, setIsError] = useState<boolean>(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsError(false);

    if (password !== confirmPassword) {
      setMessage('Passwords do not match.');
      setIsError(true);
      return;
    }

    if (password.length < 8) {
      setMessage('Password should be at least 8 characters long.');
      setIsError(true);
      return;
    }

    try {
      const response = await fetch('/api/v1/auth/register', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password, role: "user" }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        setMessage(errorData.detail || 'Registration failed');
        setIsError(true);
        return;
      }

      const data: RegistrationResponse = await response.json();
      setMessage(data.message || 'Registration successful! Please check your email.');
      setIsError(false);

      setTimeout(() => {
        window.location.href = '/login';
      }, 3000);
    } catch (error) {
      clientLogger.error({
        event: "auth.registration_request_failed",
        message: "Registration request failed",
        error,
      });
      setMessage('An error occurred.');
      setIsError(true);
    }
  };

  return (
    <AuthLayout title="Register">
          <form onSubmit={handleRegister} className="space-y-4">
            {/* Email */}
            <div>
              <Label htmlFor="email" className={AUTH_LABEL_CLASS}>E-Mail</Label>
              <Input
                id="email"
                type="email"
                placeholder="E-Mail"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            {/* Password */}
            <div className="relative">
              <Label htmlFor="password" className={AUTH_LABEL_CLASS}>Passwort</Label>
              <Input
                id="password"
                type={showPassword ? 'text' : 'password'}
                placeholder="Passwort"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="absolute right-3 top-9 text-gray-500"
                onClick={() => setShowPassword(!showPassword)}
                aria-label="Passwort anzeigen"
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>


            {/* Confirm Password */}
              <div className="relative">
              <Label htmlFor="confirmPassword" className={AUTH_LABEL_CLASS}>Confirm password</Label>
              <Input
                id="confirmPassword"
                type={showConfirmPassword ? 'text' : 'password'}
                placeholder="Passwort bestätigen"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="absolute right-3 top-9 text-gray-500"
                onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                aria-label="Passwort anzeigen"
              >
                {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>

            {/* Submit */}
            <Button
              type="submit"
              className={AUTH_SUBMIT_BUTTON_CLASS}
            >
              REGISTER
            </Button>

            {/* Message */}
            {message && (
              <p className={`mt-2 text-center text-sm ${isError ? 'text-red-600' : 'text-green-600'}`}>
                {message}
              </p>
            )}

            {/* Already have account */}
            <div className="text-xs mt-4 text-center">
              <p>
                Already have an account?{' '}
                <Link to="/login" className="text-blue-600 hover:underline">
                  Login here
                </Link>
              </p>
            </div>
          </form>
    </AuthLayout>
  );
};

export default Registration;
