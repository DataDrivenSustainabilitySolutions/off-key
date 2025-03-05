import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import axios from 'axios';

const Verification: React.FC = () => {
    const location = useLocation();
    const [status, setStatus] = useState<string>('Verifying...');
    const queryParams = new URLSearchParams(location.search);
    const token = queryParams.get('token');

    useEffect(() => {
        if (token) {
            axios.get(`http://localhost:8000/verify?token=${token}`)
                .then(response => {
                    setStatus('Email verified successfully!');
                })
                .catch(error => {
                    setStatus('Verification failed. Please try again.');
                });
        } else {
            setStatus('Invalid verification link.');
        }
    }, [token]);

    return (
        <div>
            <h1>{status}</h1>
        </div>
    );
};

export default VerifyEmail;