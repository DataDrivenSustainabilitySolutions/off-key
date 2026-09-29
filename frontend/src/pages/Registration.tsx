import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { AuthLayout, AUTH_LINK_CLASS, AUTH_ERROR_CLASS, AUTH_SUBMIT_BUTTON_CLASS } from "@/components/AuthLayout";
import { validatePassword, validatePasswordConfirmation } from "@/lib/validation";
import { apiUtils } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";

export default function Registration() {
  const location = useLocation();
  const token = new URLSearchParams(location.hash.slice(1)).get("token");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);

  const accept = async (event: React.FormEvent) => {
    event.preventDefault();
    const validation = [validatePassword(password), validatePasswordConfirmation(password, confirmation)].find((result) => !result.isValid);
    if (validation) { setError(validation.message ?? "Check your password."); return; }
    setBusy(true);
    setError("");
    try {
      await apiUtils.post("/v1/auth/accept-invitation", { token, password });
      setAccepted(true);
      window.history.replaceState(null, "", location.pathname);
    } catch (error) {
      setError(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title="Accept invitation">
      {accepted ? <p role="status">Your account is ready. <Link to="/login" className={AUTH_LINK_CLASS}>Log in</Link></p> : !token ? (
        <p className="text-sm">Ask your administrator for an invitation link.</p>
      ) : (
        <form onSubmit={accept} className="space-y-4">
          <p className="text-sm text-muted-foreground">Use at least 12 characters.</p>
          <div className="grid gap-2"><Label htmlFor="password">Password</Label><Input id="password" type="password" autoComplete="new-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></div>
          <div className="grid gap-2"><Label htmlFor="confirmPassword">Confirm password</Label><Input id="confirmPassword" type="password" autoComplete="new-password" required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></div>
          {error && <p role="alert" className={AUTH_ERROR_CLASS}>{error}</p>}
          <Button className={AUTH_SUBMIT_BUTTON_CLASS} disabled={busy} type="submit">Accept invitation</Button>
        </form>
      )}
    </AuthLayout>
  );
}
