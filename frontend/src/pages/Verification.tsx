import { useEffect, useState } from 'react';
import { useLocation, Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import {
  AuthLayout,
  AUTH_SUBMIT_BUTTON_CLASS,
} from '@/components/AuthLayout';
import { apiUtils } from '@/lib/api-client';
import { API_CONFIG } from '@/lib/api-config';
import { clientLogger } from '@/lib/logger';

const VerificationContent: React.FC<{ token: string | null }> = ({ token }) => {
    const [status, setStatus] = useState<string>(
        token ? 'Verifying your email...' : 'Invalid verification link.'
    );
    const [isSuccess, setIsSuccess] = useState<boolean>(false);
    const [isLoading, setIsLoading] = useState<boolean>(Boolean(token));

    useEffect(() => {
        if (!token) {
            return;
        }

        let isMounted = true;
        const controller = new AbortController();

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

        return () => {
            isMounted = false;
            controller.abort();
        };
    }, [token]);

    return (
        <AuthLayout title="Email Verification" contentClassName="text-center space-y-4">
            <div className={`text-lg ${isSuccess ? 'text-green-600' : isLoading ? 'text-blue-600' : 'text-red-600'}`}>
                {status}
            </div>

            {isSuccess && (
                <Link to="/login">
                    <Button className={AUTH_SUBMIT_BUTTON_CLASS}>
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
        </AuthLayout>
    );
};

const Verification: React.FC = () => {
    const location = useLocation();
    const queryParams = new URLSearchParams(location.search);
    const token = queryParams.get('token');

    return <VerificationContent key={token ?? 'missing'} token={token} />;
};

export default Verification;
