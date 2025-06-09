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
      setError('Kein Token in der URL gefunden.');
    }
  }, [searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage('');
    setError('');

    if (!token) {
      setError('Token fehlt.');
      return;
    }

    if (newPassword.length < 8) {
      setError('Das Passwort muss mindestens 8 Zeichen lang sein.');
      return;
    }

    try {
      const response = await fetch('http://localhost:8000/v1/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: newPassword }),
      });

      if (!response.ok) {
        const data = await response.json();
        setError(data.detail || 'Fehler beim Zurücksetzen des Passworts.');
        return;
      }

      setMessage('Passwort erfolgreich zurückgesetzt. Du wirst weitergeleitet...');
      setTimeout(() => navigate('/login'), 3000); // nach 3 Sekunden zur Login-Seite
    } catch (err) {
      setError('Serverfehler. Bitte versuche es später erneut.');
      console.error(err);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100 px-4">
      <Card className="w-full max-w-md p-6">
        <CardHeader>
          <CardTitle className="text-center text-2xl">Passwort zurücksetzen</CardTitle>
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
                  Neues Passwort
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
                  Password bestätigen
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
                Passwort zurücksetzen
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default ResetPassword;
