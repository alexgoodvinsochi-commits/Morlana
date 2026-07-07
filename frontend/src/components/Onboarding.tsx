import { useState } from 'react';
import { apiPost } from '../api/client';

interface Props {
  initData: string;
  onComplete: (data: { login: string; real_name: string }) => void;
}

type Step = 'auth' | 'form';

export default function Onboarding({ initData, onComplete }: Props) {
  const [step, setStep] = useState<Step>('auth');
  const [realName, setRealName] = useState('');
  const [gender, setGender] = useState('');
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

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

    try {
      await apiPost(
        '/api/v1/auth/register',
        {
          initData,
          real_name: realName.trim(),
          gender,
          login: login.trim(),
          password,
        },
      );
      onComplete({ login: login.trim(), real_name: realName.trim() });
    } catch (err: any) {
      const msg = err?.message || '';
      if (msg.includes('400')) {
        setError('Этот логин уже занят');
      } else {
        setError('Ошибка сервера. Попробуйте позже.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!login.trim()) {
      setError('Придумайте логин');
      return;
    }
    if (login.length < 3) {
      setError('Логин минимум 3 символа');
      return;
    }
    if (!password) {
      setError('Придумайте пароль');
      return;
    }
    if (password.length < 4) {
      setError('Пароль минимум 4 символа');
      return;
    }
    setError('');
    setStep('form');
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

        <button type="submit" disabled={loading} className="submit-btn">
          {loading ? 'Загрузка...' : 'Создать аккаунт'}
        </button>
      </form>
    </div>
  );
}
