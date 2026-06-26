import { useState } from 'react';
import { apiPost } from '../api/client';
import { getCardImage, getCardName } from '../utils/cardMap';

interface Props {
  initData: string;
  onDraw: (cards: number[], layoutType: string) => void;
}

export default function TarotDraw({ initData, onDraw }: Props) {
  const [loading, setLoading] = useState(false);
  const [drawnCards, setDrawnCards] = useState<number[] | null>(null);
  const [flipped, setFlipped] = useState(false);
  const [error, setError] = useState('');

  const handleDraw = async (count: number) => {
    setLoading(true);
    setError('');
    setDrawnCards(null);
    setFlipped(false);
    try {
      const data = await apiPost<{ cards: number[]; layout_type: string }>(
        '/api/v1/tarot/draw',
        { layout_type: `${count}_cards`, count },
        initData,
      );
      setDrawnCards(data.cards);
      setTimeout(() => setFlipped(true), 100);
      setTimeout(() => onDraw(data.cards, data.layout_type), 1200);
    } catch {
      setError('Не удалось разложить карты. Попробуйте ещё раз.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="tarot-draw">
      <h2>Выберите расклад</h2>

      {drawnCards && (
        <div className="card-row">
          {drawnCards.map((card, i) => (
            <div key={i} className={`card-slot ${flipped ? 'flipped' : ''}`}>
              <div className="card-inner">
                <div className="card-back">
                  <div className="card-back-pattern" />
                </div>
                <div className="card-front">
                  <img src={getCardImage(card)} alt={getCardName(card)} loading="eager" />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="error-msg">
          <p>{error}</p>
          <button onClick={() => handleDraw(3)}>Попробовать снова</button>
        </div>
      )}

      {!drawnCards && !error && (
        <div className="layout-options">
          <button onClick={() => handleDraw(1)} disabled={loading}>
            {loading ? <><span className="spinner" /> Расклад...</> : '1 карта'}
          </button>
          <button onClick={() => handleDraw(3)} disabled={loading}>
            {loading ? <><span className="spinner" /> Расклад...</> : '3 карты'}
          </button>
          <button onClick={() => handleDraw(10)} disabled={loading}>
            {loading ? <><span className="spinner" /> Расклад...</> : '10 карт'}
          </button>
        </div>
      )}
    </div>
  );
}
