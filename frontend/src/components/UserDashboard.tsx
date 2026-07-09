import { useState, useEffect } from 'react';
import { apiGet } from '../api/client';
import ReadingHistory from './ReadingHistory';
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
}

export default function UserDashboard({ initData, userLogin, onLogout, onNewReading }: Props) {
  const [user, setUser] = useState<UserData | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadUser = async () => {
      try {
        const data = await apiGet<UserData>(
          `/api/v1/auth/me?login=${userLogin}`,
          initData,
        );
        setUser(data);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    };
    loadUser();
  }, [initData, userLogin]);

  if (showHistory) {
    return <ReadingHistory initData={initData} onBack={() => setShowHistory(false)} />;
  }

  if (loading) {
    return (
      <div className="dashboard">
        <div className="reading-loading">
          <span className="spinner" /> Загрузка...
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <div className="user-avatar">
          {user?.real_name?.charAt(0).toUpperCase() || '?'}
        </div>
        <h2>{user?.real_name || 'Пользователь'}</h2>
        <p className="user-login">@{user?.login}</p>
        {user?.gender && (
          <p className="user-gender">{user.gender === 'female' ? 'Женский' : 'Мужской'}</p>
        )}
      </div>

      <div className="dashboard-actions">
        <button onClick={onNewReading} className="dashboard-btn primary">
          Новый расклад
        </button>
        <button onClick={() => setShowHistory(true)} className="dashboard-btn">
          Мои расклады
        </button>
        <button onClick={onLogout} className="dashboard-btn danger">
          Выйти
        </button>
      </div>
    </div>
  );
}
