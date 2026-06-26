import { useState } from 'react';
import { useTelegram } from '../hooks/useTelegram';
import { apiPost } from '../api/client';

interface Props {
  freeRequestsLeft: number;
}

export default function Paywall({ freeRequestsLeft }: Props) {
  const { webApp, initData } = useTelegram();
  const [loading, setLoading] = useState<string | null>(null);

  const handleSubscribe = async (plan: 'monthly' | 'quarterly') => {
    if (!webApp || !initData) {
      alert('Откройте приложение в Telegram');
      return;
    }

    setLoading(plan);
    try {
      const { invoice_link } = await apiPost<{ invoice_link: string }>(
        '/api/v1/payments/create-invoice',
        { plan },
        initData,
      );

      webApp.openInvoice(invoice_link, (status) => {
        if (status === 'paid') {
          alert('Оплата прошла успешно! Подписка активирована.');
          window.location.reload();
        } else if (status === 'cancelled') {
          // User cancelled
        } else {
          alert('Оплата не прошла. Попробуйте ещё раз.');
        }
        setLoading(null);
      });
    } catch (error) {
      console.error('Payment error:', error);
      alert('Ошибка при создании платежа. Попробуйте позже.');
      setLoading(null);
    }
  };

  return (
    <div className="paywall">
      <h2>Бесплатные расклады закончились</h2>
      <p>
        У вас осталось {freeRequestsLeft} бесплатных вопросов.
      </p>
      <p>Оформите подписку для неограниченных раскладов с премиальными моделями ИИ.</p>

      <div className="plans">
        <div className="plan">
          <h3>Месяц</h3>
          <p className="price">299 ₽</p>
          <ul>
            <li>Безлимитные расклады</li>
            <li>Премиальные модели ИИ</li>
            <li>Глубокие разборы</li>
          </ul>
          <button
            onClick={() => handleSubscribe('monthly')}
            disabled={loading !== null}
          >
            {loading === 'monthly' ? 'Загрузка...' : 'Оформить'}
          </button>
        </div>

        <div className="plan">
          <h3>3 месяца</h3>
          <p className="price">699 ₽</p>
          <ul>
            <li>Всё из "Месяц"</li>
            <li>Скидка 22%</li>
          </ul>
          <button
            onClick={() => handleSubscribe('quarterly')}
            disabled={loading !== null}
          >
            {loading === 'quarterly' ? 'Загрузка...' : 'Оформить'}
          </button>
        </div>
      </div>
    </div>
  );
}
