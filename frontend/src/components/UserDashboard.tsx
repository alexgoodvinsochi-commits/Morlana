import { useState, useEffect } from 'react';
import { apiGet, ApiError } from '../api/client';
import '../styles/dashboard.css';

interface UserData {
  telegram_id: number;
  real_name: string;
  gender: string | null;
  login: string;
}

interface Props {
  initData: string;
  userLogin: string;
  onLogout: () => void;
  onNewReading: () => void;
  onOpenHistory: () => void;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) {
      return 'Не удалось подтвердить Telegram. Откройте Morlana из Telegram.';
    }
    if (err.status === 429) {
      return 'Слишком много попыток. Подождите минуту.';
    }
  }
  return 'Не удалось загрузить профиль. Попробуйте позже.';
}

export default function UserDashboard({
  initData,
  userLogin,
  onLogout,
  onNewReading,
  onOpenHistory,
}: Props) {
  const [user, setUser] = useState<UserData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const loadUser = async () => {
      setLoading(true);
      setError('');
      try {
        const data = await apiGet<UserData>('/api/v1/auth/me', initData);
        if (cancelled) return;
        if (data.login !== userLogin) {
          // The Telegram account no longer matches the login we are showing.
          onLogout();
          return;
        }
        setUser(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          onLogout();
          return;
        }
        setUser(null);
        setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    loadUser();

    return () => {
      cancelled = true;
    };
    // onLogout is intentionally not a dependency: it is recreated on every
    // App render and would restart the request loop.
  }, [initData, userLogin, attempt]);

  if (loading) {
    return (
      <div className="dashboard">
        <div className="reading-loading">
          <span className="spinner" /> Загрузка...
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="dashboard">
        <div className="error-msg">
          <p>{error || 'Не удалось загрузить профиль. Попробуйте позже.'}</p>
          <button onClick={() => setAttempt((n) => n + 1)}>Повторить</button>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <div className="user-avatar">
          {user.real_name?.charAt(0).toUpperCase() || '?'}
        </div>
        <h2>{user.real_name}</h2>
        <p className="user-login">@{user.login}</p>
        {user.gender && (
          <p className="user-gender">{user.gender === 'female' ? 'Женский' : 'Мужской'}</p>
        )}
      </div>

      <div className="dashboard-actions">
        <button onClick={onNewReading} className="dashboard-btn primary">
          Новый расклад
        </button>
        <button onClick={onOpenHistory} className="dashboard-btn">
          Мои расклады
        </button>
        <button onClick={onLogout} className="dashboard-btn danger">
          Выйти
        </button>
      </div>
    </div>
  );
}
