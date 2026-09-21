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
  onComplete: (data: { login: string; real_name: string }) => void;
  onBack: () => void;
}

type Step = 'auth' | 'form';
type Gender = '' | 'male' | 'female';

/* Mirrors the server-side constraints (routes/auth.py RegisterRequest) */
const LOGIN_PATTERN = /^[A-Za-z0-9_.-]+$/;

export default function Onboarding({ initData, onComplete, onBack }: Props) {
  const [step, setStep] = useState<Step>('auth');
  const [realName, setRealName] = useState('');
  const [gender, setGender] = useState<Gender>('');
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showLoginLink, setShowLoginLink] = useState(false);

  const handlePersonalSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!realName.trim()) {
      setError('Пожалуйста, введите ваше имя');
      return;
    }
    if (!gender) {
      setError('Пожалуйста, выберите пол');
      return;
    }

    setLoading(true);
    setError('');
    setShowLoginLink(false);

    try {
      const data = await apiPost<AuthResponse>(
        '/api/v1/auth/register',
        {
          real_name: realName.trim(),
          gender,
          login: login.trim(),
          password,
        },
        initData,
      );
      onComplete({ login: data.login, real_name: data.real_name });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.detail === 'Login already taken') {
          setStep('auth');
          setError('Этот логин уже занят');
        } else if (err.status === 409) {
          // The only other 409 is "Account already registered"
          setError('У этого Telegram-аккаунта уже есть логин. Войдите.');
          setShowLoginLink(true);
        } else if (err.status === 422) {
          setError('Проверьте введённые данные');
        } else if (err.status === 401) {
          setError('Не удалось подтвердить Telegram. Откройте Morlana из Telegram.');
        } else if (err.status === 429) {
          setError('Слишком много попыток. Подождите минуту.');
        } else {
          setError('Ошибка сети или сервера. Попробуйте позже.');
        }
      } else {
        setError('Ошибка сети или сервера. Попробуйте позже.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedLogin = login.trim();
    if (!trimmedLogin) {
      setError('Придумайте логин');
      return;
    }
    if (trimmedLogin.length < 3 || trimmedLogin.length > 32) {
      setError('Логин: от 3 до 32 символов');
      return;
    }
    if (!LOGIN_PATTERN.test(trimmedLogin)) {
      setError('Логин: только латиница, цифры и . _ -');
      return;
    }
    if (!password) {
      setError('Придумайте пароль');
      return;
    }
    if (password.length < 6) {
      setError('Пароль минимум 6 символов');
      return;
    }
    if (password.length > 128) {
      setError('Пароль не длиннее 128 символов');
      return;
    }
    setError('');
    setShowLoginLink(false);
    setStep('form');
  };

  const handleBackToAuth = () => {
    setError('');
    setShowLoginLink(false);
    setStep('auth');
  };

  if (step === 'auth') {
    return (
      <div className="onboarding">
        <h1>Создайте аккаунт</h1>
        <p>Придумайте логин и пароль для входа</p>

        <form onSubmit={handleAuthSubmit}>
          <div className="field">
            <label>Логин</label>
            <input
              type="text"
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              placeholder="Придумайте логин"
              autoFocus
            />
          </div>

          <div className="field">
            <label>Пароль</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Придумайте пароль"
            />
          </div>

          {error && <p className="error">{error}</p>}

          <button type="submit" className="submit-btn">
            Далее
          </button>
        </form>

        <p className="auth-link">
          Уже есть аккаунт?{' '}
          <button type="button" className="link-btn" onClick={onBack}>
            Войти
          </button>
        </p>
      </div>
    );
  }

  return (
    <div className="onboarding">
      <h1>Расскажите о себе</h1>

      <form onSubmit={handlePersonalSubmit}>
        <div className="field">
          <label>Ваше имя</label>
          <input
            type="text"
            value={realName}
            onChange={(e) => setRealName(e.target.value)}
            placeholder="Как к вам обращаться?"
            autoFocus
          />
        </div>

        <div className="field">
          <label>Пол</label>
          <div className="gender-options">
            <button
              type="button"
              className={`gender-btn ${gender === 'female' ? 'selected' : ''}`}
              onClick={() => setGender('female')}
            >
              Женский
            </button>
            <button
              type="button"
              className={`gender-btn ${gender === 'male' ? 'selected' : ''}`}
              onClick={() => setGender('male')}
            >
              Мужской
            </button>
          </div>
        </div>

        {error && <p className="error">{error}</p>}

        {showLoginLink && (
          <p className="auth-link">
            <button type="button" className="link-btn" onClick={onBack}>
              Войти
            </button>
          </p>
        )}

        <button type="submit" disabled={loading} aria-busy={loading} className="submit-btn">
          {loading ? 'Загрузка...' : 'Создать аккаунт'}
        </button>

        <button type="button" className="back-btn" onClick={handleBackToAuth} disabled={loading}>
          Назад
        </button>
      </form>
    </div>
  );
}
