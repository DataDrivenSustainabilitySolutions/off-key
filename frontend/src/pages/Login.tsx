import React, { useState } from "react";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useNavigate } from "react-router-dom";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import {
  AuthLayout,
  AUTH_LABEL_CLASS,
  AUTH_SUBMIT_BUTTON_CLASS,
} from "@/components/AuthLayout";
import { API_CONFIG, getApiUrl } from "@/lib/api-config";
import { validateEmail, validatePassword, sanitizeInput } from "@/lib/validation";
import { Eye, EyeOff } from "lucide-react";
import { clientLogger } from "@/lib/logger";

interface LoginResponse {
  access_token: string;
  token_type: string;
}

const Login: React.FC = () => {
  const [rememberMe, setRememberMe] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [message, setMessage] = useState("");
  const [emailError, setEmailError] = useState<string | undefined>();
  const [passwordError, setPasswordError] = useState<string | undefined>();
  const navigate = useNavigate();
  const { login } = useAuth();
  // Removed sync functions - frontend is now a viewer only

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();

    // Clear previous errors
    setEmailError(undefined);
    setPasswordError(undefined);
    setMessage("");

    // Validate inputs
    const emailValidation = validateEmail(email);
    const passwordValidation = validatePassword(password);

    if (!emailValidation.isValid) {
      setEmailError(emailValidation.message);
      return;
    }

    if (!passwordValidation.isValid) {
      setPasswordError(passwordValidation.message);
      return;
    }

    try {
      // Sanitize inputs before sending
      const sanitizedEmail = sanitizeInput(email);
      const sanitizedPassword = password; // Don't sanitize password as it might contain special chars
      const response = await fetch(getApiUrl(API_CONFIG.ENDPOINTS.AUTH.LOGIN), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: sanitizedEmail, password: sanitizedPassword }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        setMessage(errorData.detail || "Login failed");
        return;
      }

      const data: LoginResponse = await response.json();

      // Use consolidated login function which handles token storage
      login(data.access_token, rememberMe);

      navigate("/");
    } catch (error) {
      clientLogger.error({
        event: "auth.login_request_failed",
        message: "Login request failed",
        error,
      });
      setMessage("An error occurred");
    }
  };

  return (
    <AuthLayout title="Login" titleProps={{ role: "heading", "aria-level": 1 }}>
      <form onSubmit={handleLogin} className="space-y-4">
        {/* E-Mail */}
        <div>
          <Label htmlFor="email" className={AUTH_LABEL_CLASS}>
            E-Mail
          </Label>
          <Input
            id="email"
            type="email"
            placeholder="E-Mail"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              if (emailError) setEmailError(undefined);
            }}
            className={emailError ? 'border-destructive' : ''}
            required
          />
          {emailError && (
            <p className="text-sm text-destructive mt-1">{emailError}</p>
          )}
        </div>

        <div className="relative">
          <Label htmlFor="password" className={AUTH_LABEL_CLASS}>
            Password
          </Label>
          <Input
            id="password"
            type={showPassword ? "text" : "password"}
            placeholder="Password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              if (passwordError) setPasswordError(undefined);
            }}
            className={passwordError ? 'border-destructive' : ''}
            required
          />
          {passwordError && (
            <p className="text-sm text-destructive mt-1 mr-10">{passwordError}</p>
          )}
          <button
            type="button"
            className="absolute right-3 top-9 text-gray-500"
            onClick={() => setShowPassword(!showPassword)}
            aria-label="Show password"
          >
            {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>

        <div className="flex items-center space-x-2 text-sm">
          <input
            type="checkbox"
            id="remember"
            className="accent-green-600"
            checked={rememberMe}
            onChange={(e) => setRememberMe(e.target.checked)}
          />
          <label htmlFor="remember">Stay logged in</label>
        </div>

        {/* Login Button */}
        <Button
          type="submit"
          className={AUTH_SUBMIT_BUTTON_CLASS}
        >
          Log in
        </Button>

        {/* Fehlermeldung oder Erfolgsnachricht */}
        {message && (
          <p
            className={`mt-2 text-center text-sm ${
              message === "Login successful!"
                ? "text-green-600"
                : "text-red-600"
            }`}
          >
            {message}
          </p>
        )}

        {/* Links */}
        <div className="text-sm text-center mt-3 space-y-1">
          <Link
            to="/forgot-password"
            className="text-blue-600 hover:underline"
          >
            Forgot password?
          </Link>
        </div>
        <div className="text-xs mt-4 text-center">
          <p>
            Not signed up yet?{" "}
            <Link to="/register" className="text-blue-600 hover:underline">
              Register here
            </Link>
          </p>
        </div>
      </form>
    </AuthLayout>
  );
};

export default Login;
