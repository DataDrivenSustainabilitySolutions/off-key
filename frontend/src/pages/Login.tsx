import React, { useState } from "react";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useNavigate } from "react-router-dom";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { waitForLogout } from "@/auth/session";
import {
  AuthLayout,
  AUTH_LINK_CLASS,
  AUTH_ERROR_CLASS,
  AUTH_SUCCESS_CLASS,

  AUTH_LABEL_CLASS,
  AUTH_SUBMIT_BUTTON_CLASS,
} from "@/components/AuthLayout";
import { API_CONFIG, getApiUrl } from "@/lib/api-config";
import { validateEmail, sanitizeInput } from "@/lib/validation";
import { Eye, EyeOff } from "lucide-react";
import { clientLogger } from "@/lib/logger";

interface LoginResponse {
  access_token: string;
  token_type: string;
  user_id?: number | string;
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
  const configuredAdminEmail = import.meta.env.VITE_LOCAL_ADMIN_EMAIL?.trim();
  const localAdminEmail = ["127.0.0.1", "localhost", "[::1]", "::1"].includes(globalThis.location.hostname)
    && configuredAdminEmail && validateEmail(configuredAdminEmail).isValid
    ? configuredAdminEmail : undefined;
  // Removed sync functions - frontend is now a viewer only

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();

    // Clear previous errors
    setEmailError(undefined);
    setPasswordError(undefined);
    setMessage("");

    // Validate inputs
    const loginEmail = localAdminEmail && email.trim() === "admin" ? localAdminEmail : email;
    const emailValidation = validateEmail(loginEmail);

    if (!emailValidation.isValid) {
      setEmailError(emailValidation.message);
      return;
    }

    if (!password) {
      setPasswordError("Password is required.");
      return;
    }

    try {
      await waitForLogout();
      // Sanitize inputs before sending
      const sanitizedEmail = sanitizeInput(loginEmail);
      const sanitizedPassword = password; // Don't sanitize password as it might contain special chars
      const response = await fetch(getApiUrl(API_CONFIG.ENDPOINTS.AUTH.LOGIN), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: sanitizedEmail, password: sanitizedPassword, remember_me: rememberMe }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        setMessage(errorData.detail || "Login failed");
        return;
      }

      const data: LoginResponse = await response.json();

      // Use consolidated login function which handles token storage
      login(data.access_token, rememberMe, data.user_id);

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
    <AuthLayout title="Login">
      <form onSubmit={handleLogin} className="space-y-4">
        {/* Email */}
        <div>
          <Label htmlFor="email" className={AUTH_LABEL_CLASS}>
            Email
          </Label>
          <Input
            id="email"
            type={localAdminEmail ? "text" : "email"}
            placeholder="Email"
            inputMode="email"
            autoComplete="username"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              if (emailError) setEmailError(undefined);
            }}
            className={emailError ? 'border-destructive' : ''}
            aria-invalid={Boolean(emailError)}
            aria-describedby={emailError ? 'email-error' : undefined}
            required
          />
          {emailError && (
            <p id="email-error" className="text-sm text-destructive mt-1">{emailError}</p>
          )}
        </div>

        <div>
          <Label htmlFor="password" className={AUTH_LABEL_CLASS}>
            Password
          </Label>
          <div className="relative">
          <Input
            id="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            placeholder="Password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              if (passwordError) setPasswordError(undefined);
            }}
            className={passwordError ? 'pr-12 border-destructive' : 'pr-12'}
            aria-invalid={Boolean(passwordError)}
            aria-describedby={passwordError ? 'password-error' : undefined}
            required
          />
          <button
            type="button"
            className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-md text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/25"
            onClick={() => setShowPassword(!showPassword)}
            aria-label={showPassword ? "Hide password" : "Show password"}
          >
            {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
          </div>
          {passwordError && (
            <p id="password-error" className="text-sm text-destructive mt-1">{passwordError}</p>
          )}
        </div>

        <div className="flex items-center space-x-2 text-sm">
          <input
            type="checkbox"
            id="remember"
            className="accent-primary"
            checked={rememberMe}
            onChange={(e) => setRememberMe(e.target.checked)}
          />
          <label htmlFor="remember">Remember this device</label>
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
                ? AUTH_SUCCESS_CLASS
                : AUTH_ERROR_CLASS
            }`}
          >
            {message}
          </p>
        )}

        {/* Links */}
        <div className="text-sm text-center mt-3 space-y-1">
          <Link
            to="/forgot-password"
            className={AUTH_LINK_CLASS}
          >
            Forgot password?
          </Link>
        </div>
      </form>
    </AuthLayout>
  );
};

export default Login;
