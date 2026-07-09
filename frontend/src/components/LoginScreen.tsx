import { useState } from 'react';
import { apiPost } from '../api/client';
import '../styles/onboarding.css';

interface Props {
  onLogin: (data: { login: string; real_name: string }) => void;
  onRegister: () => void;
}

export default function LoginScreen({ onLogin, onRegister }: Props) {
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!login.trim() || !password) {
      setError('Заполните все поля');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const data = await apiPost<{ real_name: string }>(
        '/api/v1/auth/login',
        { login: login.trim(), password },
      );
      onLogin({ login: login.trim(), real_name: data.real_name });
    } catch {
      setError('Неверный логин или пароль');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="onboarding">
      <div className="onboarding-welcome">
        <h1>Morlana</h1>
      </div>

      <form onSubmit={handleSubmit}>
        <div className="field">
          <label>Логин</label>
          <input
            type="text"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            placeholder="Ваш логин"
            autoFocus
          />
        </div>

        <div className="field">
          <label>Пароль</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Ваш пароль"
          />
        </div>

        {error && <p className="error">{error}</p>}

        <button type="submit" disabled={loading} className="submit-btn">
          {loading ? 'Загрузка...' : 'Войти'}
        </button>
      </form>

      <p className="auth-link">
        Нет аккаунта?{' '}
        <button type="button" className="link-btn" onClick={onRegister}>
          Зарегистрироваться
        </button>
      </p>
    </div>
  );
}
