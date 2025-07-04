import { useEffect } from 'react';
import { useAuth } from '@/auth/AuthContext';
import { useFetch } from '@/dataFetch/UseFetch';

const StartupSync: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  const { syncChargers, syncTelemetry } = useFetch();

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      syncChargers();
      syncTelemetry();
    }
  }, [isLoading, isAuthenticated]);

  return null; 
};

export default StartupSync;