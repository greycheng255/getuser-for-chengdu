import React, { useEffect, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { Spin } from 'antd';
import { checkAuth, authStorage } from '../api/auth';

interface AuthGuardProps {
  children: React.ReactNode;
}

const AuthGuard: React.FC<AuthGuardProps> = ({ children }) => {
  const location = useLocation();
  const token = authStorage.getToken();
  const [checking, setChecking] = useState(true);
  const [valid, setValid] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!token) {
      setChecking(false);
      setValid(false);
      return;
    }
    checkAuth()
      .then((res) => {
        if (cancelled) return;
        if (res?.valid && res.user) {
          authStorage.setUser(res.user);
          setValid(true);
        } else {
          authStorage.clear();
          setValid(false);
        }
      })
      .catch(() => {
        if (cancelled) return;
        authStorage.clear();
        setValid(false);
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (checking) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Spin size="large" tip="正在校验登录状态..." />
      </div>
    );
  }

  if (!token || !valid) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
};

export default AuthGuard;
