import { useState } from 'react';
import { apiPost, ApiError } from '../api/client';
import '../styles/onboarding.css';

interface AuthResponse {
  telegram_id: number;
  real_name: string;
  gender: string | null;
  login: string;
}

interface Props {
  initData: string;
  onLogin: (data: { login: string; real_name: string }) => void;
  onRegister: () => void;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) {
      return err.detail === 'Invalid login or password'
        ? 'Неверный логин или пароль'
        : 'Не удалось подтвердить Telegram. Откройте Morlana из Telegram.';
    }
    if (err.status === 429) {
      return 'Слишком много попыток. Подождите минуту.';
    }
  }
  return 'Ошибка сети или сервера. Попробуйте позже.';
}

export default function LoginScreen({ initData, onLogin, onRegister }: Props) {
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
      const data = await apiPost<AuthResponse>(
        '/api/v1/auth/login',
        { login: login.trim(), password },
        initData,
      );
      onLogin({ login: data.login, real_name: data.real_name });
    } catch (err) {
      setError(errorMessage(err));
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

        <button type="submit" disabled={loading} aria-busy={loading} className="submit-btn">
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
