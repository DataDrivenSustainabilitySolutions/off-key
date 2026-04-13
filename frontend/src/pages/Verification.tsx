import { useEffect, useState } from 'react';
import { useLocation, Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { apiUtils } from '@/lib/api-client';
import { API_CONFIG } from '@/lib/api-config';
import { clientLogger } from '@/lib/logger';

const Verification: React.FC = () => {
    const location = useLocation();
    const [status, setStatus] = useState<string>('Verifying your email...');
    const [isSuccess, setIsSuccess] = useState<boolean>(false);
    const [isLoading, setIsLoading] = useState<boolean>(true);
    const queryParams = new URLSearchParams(location.search);
    const token = queryParams.get('token');

    useEffect(() => {
        let isMounted = true;
        const controller = new AbortController();

        if (token) {
            apiUtils.get(`${API_CONFIG.ENDPOINTS.AUTH.VERIFY_EMAIL}?token=${token}`, {
                signal: controller.signal,
            })
                .then(() => {
                    if (!isMounted) {
                        return;
                    }
                    setStatus('Email verified successfully!');
                    setIsSuccess(true);
                    setIsLoading(false);
                })
                .catch((error) => {
                    if (!isMounted || controller.signal.aborted) {
                        return;
                    }
                    clientLogger.error({
                        event: 'auth.email_verification_failed',
                        message: 'Email verification request failed',
                        context: { hasToken: true },
                        error,
                    });
                    setStatus('Verification failed. Please try again.');
                    setIsSuccess(false);
                    setIsLoading(false);
                })
        } else {
            setStatus('Invalid verification link.');
            setIsSuccess(false);
            setIsLoading(false);
        }

        return () => {
            isMounted = false;
            controller.abort();
        };
    }, [token]);

    return (
        <div className="min-h-screen flex items-center justify-center bg-gray-100 px-4">
            <Card className="w-full max-w-md p-6">
                <CardHeader>
                    <CardTitle className="text-center text-2xl">
                        Email Verification
                    </CardTitle>
                </CardHeader>
                <CardContent className="text-center space-y-4">
                    <div className={`text-lg ${isSuccess ? 'text-green-600' : isLoading ? 'text-blue-600' : 'text-red-600'}`}>
                        {status}
                    </div>

                    {isSuccess && (
                        <Link to="/login">
                            <Button className="w-full bg-gradient-to-r from-slate-400 to-slate-300 text-white font-semibold rounded-full transition-all duration-200 hover:bg-gradient-to-r hover:from-slate-500 hover:to-slate-400 hover:scale-105 cursor-pointer">
                                Go to Login
                            </Button>
                        </Link>
                    )}

                    {!isLoading && !isSuccess && (
                        <div className="space-y-2">
                            <Link to="/register">
                                <Button variant="outline" className="w-full">
                                    Register Again
                                </Button>
                            </Link>
                            <p className="text-sm text-gray-600">
                                Need help? Contact support
                            </p>
                        </div>
                    )}
                </CardContent>
            </Card>
        </div>
    );
};

export default Verification;
