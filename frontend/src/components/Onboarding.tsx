import { useState } from 'react';
import { apiPost } from '../api/client';

interface Props {
  initData: string;
  onComplete: (data: { zodiac_sign: string; greeting: string; free_requests_left: number }) => void;
}

type Step = 'welcome' | 'form';

export default function Onboarding({ initData, onComplete }: Props) {
  const [step, setStep] = useState<Step>('welcome');
  const [realName, setRealName] = useState('');
  const [gender, setGender] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
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
      const data = await apiPost<{ zodiac_sign: string; greeting: string; free_requests_left: number }>(
        '/api/v1/astrology/bonus',
        {
          initData,
          real_name: realName.trim(),
          gender,
        },
      );
      onComplete(data);
    } catch {
      setError('Ошибка сервера. Попробуйте позже.');
    } finally {
      setLoading(false);
    }
  };

  if (step === 'welcome') {
    return (
      <div className="onboarding">
        <div className="onboarding-welcome">
          <h1>Morlana</h1>
          <p>ИИ-таролог, который поможет вам заглянуть за горизонт событий</p>
          <button onClick={() => setStep('form')}>Начать расклад</button>
        </div>
      </div>
    );
  }

  return (
    <div className="onboarding">
      <h1>Расскажите о себе</h1>
      <p>Чтобы расклад был точнее, расскажите немного о себе</p>

      <form onSubmit={handleSubmit}>
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
          {loading ? 'Загрузка...' : 'Начать расклад'}
        </button>
      </form>
    </div>
  );
}
