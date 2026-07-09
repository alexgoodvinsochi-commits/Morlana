import { useState, useEffect } from 'react';
import { apiGet } from '../api/client';
import { getCardImage, getCardName } from '../utils/cardMap';
import '../styles/history.css';

interface CycleHistory {
  cycle_number: number;
  question: string;
  card_id: number;
  card_name: string | null;
}

interface ReadingHistoryItem {
  session_id: string;
  spread_name: string;
  created_at: string;
  cycle_count: number;
  synthesis: string | null;
  cycles: CycleHistory[];
}

interface Props {
  initData: string;
  onBack: () => void;
}

export default function ReadingHistory({ initData, onBack }: Props) {
  const [readings, setReadings] = useState<ReadingHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    const loadHistory = async () => {
      try {
        const data = await apiGet<{ readings: ReadingHistoryItem[] }>(
          '/api/v1/tarot/reading/history',
          initData,
        );
        setReadings(data.readings);
      } catch {
        setError('Не удалось загрузить историю.');
      } finally {
        setLoading(false);
      }
    };
    loadHistory();
  }, [initData]);

  if (loading) return <div className="reading-loading"><span className="spinner" /> Загрузка...</div>;
  if (error) return <div className="error-msg"><p>{error}</p><button onClick={onBack}>Назад</button></div>;

  return (
    <div className="reading-history-screen">
      <h2>Мои расклады</h2>
      <button onClick={onBack} className="exit-btn">Назад</button>

      {readings.length === 0 ? (
        <p className="empty-history">У вас пока нет раскладов</p>
      ) : (
        readings.map((reading) => (
          <div key={reading.session_id} className="history-item">
            <div
              className="history-item-header"
              onClick={() => setExpanded(expanded === reading.session_id ? null : reading.session_id)}
            >
              <span className="history-date">
                {new Date(reading.created_at).toLocaleDateString('ru-RU')}
              </span>
              <span className="history-cycles">{reading.cycle_count} циклов</span>
              <span className="history-expand">{expanded === reading.session_id ? '▲' : '▼'}</span>
            </div>

            {expanded === reading.session_id && (
              <div className="history-item-details">
                {reading.cycles.map((cycle) => (
                  <div key={cycle.cycle_number} className="history-cycle">
                    <div className="history-cycle-header">
                      <span className="cycle-number">Цикл {cycle.cycle_number}</span>
                      <img
                        src={getCardImage(cycle.card_id)}
                        alt={getCardName(cycle.card_id)}
                        className="history-card-thumb"
                      />
                    </div>
                    <p className="history-question">{cycle.question}</p>
                    <p className="history-card-name">{cycle.card_name || getCardName(cycle.card_id)}</p>
                  </div>
                ))}

                {reading.synthesis && (
                  <div className="history-synthesis">
                    <h4>Синтез</h4>
                    <p>{reading.synthesis}</p>
                  </div>
                )}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
