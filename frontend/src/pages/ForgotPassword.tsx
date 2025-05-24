import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

const ForgotPassword: React.FC = () => {
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch('http://localhost:8000/v1/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      setMessage(data.message);
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    } catch (error) {
      setMessage('Fehler beim Senden der Anfrage.');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100 px-4">
      <Card className="w-full max-w-md p-6">
        <CardHeader>
          <CardTitle className="text-center text-2xl">Passwort vergessen</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email Input */}
            <div>
              <Label htmlFor="email" className="mb-1 block text-sm">E-Mail</Label>
              <Input
                id="email"
                type="email"
                placeholder="Deine E-Mail-Adresse"
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
              Password zurücksetzen
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
