import { useState } from 'react';
import { apiPost } from '../api/client';

interface Props {
  initData: string;
  onComplete: (data: { zodiac_sign: string; greeting: string; free_requests_left: number }) => void;
}

export default function Onboarding({ initData, onComplete }: Props) {
  const [realName, setRealName] = useState('');
  const [birthDate, setBirthDate] = useState('');
  const [birthTime, setBirthTime] = useState('');
  const [birthLocation, setBirthLocation] = useState('');
  const [geoLoading, setGeoLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleDetectLocation = () => {
    if (!navigator.geolocation) {
      setError('Геолокация не поддерживается');
      return;
    }
    setGeoLoading(true);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        try {
          const { latitude, longitude } = position.coords;
          const res = await fetch(
            `https://nominatim.openstreetmap.org/reverse?format=json&lat=${latitude}&lon=${longitude}&accept-language=ru`
          );
          const data = await res.json();
          const city = data.address?.city || data.address?.town || data.address?.village || data.address?.state || '';
          const country = data.address?.country || '';
          setBirthLocation(city ? `${city}, ${country}` : country);
        } catch {
          setError('Не удалось определить город');
        } finally {
          setGeoLoading(false);
        }
      },
      () => {
        setGeoLoading(false);
        setError('Разрешите доступ к геолокации или введите город вручную');
      },
      { timeout: 10000 }
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!realName || !birthDate) {
      setError('Заполните имя и дату рождения');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const data = await apiPost<{ zodiac_sign: string; greeting: string; free_requests_left: number }>('/api/v1/astrology/bonus', {
        initData,
        real_name: realName,
        birth_date: birthDate,
        birth_time: birthTime || null,
        birth_location: birthLocation || null,
      });
      onComplete(data);
    } catch {
      setError('Ошибка сервера. Попробуйте позже.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="onboarding">
      <h1>Добро пожаловать в Morlana</h1>
      <p>Расскажите о себе, чтобы получить персональный астро-разбор</p>

      <form onSubmit={handleSubmit}>
        <div className="field">
          <label>Ваше имя</label>
          <input
            type="text"
            value={realName}
            onChange={(e) => setRealName(e.target.value)}
            placeholder="Как к вам обращаться?"
          />
        </div>

        <div className="field">
          <label>Дата рождения</label>
          <input
            type="date"
            value={birthDate}
            onChange={(e) => setBirthDate(e.target.value)}
          />
        </div>

        <div className="field">
          <label>Время рождения (необязательно)</label>
          <input
            type="time"
            value={birthTime}
            onChange={(e) => setBirthTime(e.target.value)}
          />
        </div>

        <div className="field">
          <label>Город рождения</label>
          <div className="location-row">
            <input
              type="text"
              value={birthLocation}
              onChange={(e) => setBirthLocation(e.target.value)}
              placeholder="Например: Москва"
            />
            <button type="button" className="geo-btn" onClick={handleDetectLocation} disabled={geoLoading}>
              {geoLoading ? '...' : 'GPS'}
            </button>
          </div>
        </div>

        {error && <p className="error">{error}</p>}

        <button type="submit" disabled={loading}>
          {loading ? 'Загрузка...' : 'Получить бонус'}
        </button>
      </form>
    </div>
  );
}
