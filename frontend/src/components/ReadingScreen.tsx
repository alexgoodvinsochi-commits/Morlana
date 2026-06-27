import { useState, useEffect, useRef, useCallback } from 'react';
import { apiPost, apiGet, apiStream } from '../api/client';
import { getCardImage, getCardName } from '../utils/cardMap';

interface Cycle {
  cards: number[];
  question: string;
  answer: string;
}

interface ReadingState {
  session_id: string;
  state: string;
  cycle_count: number;
  max_cycles: number;
  cycles: Cycle[];
  current_question: string | null;
  current_card: number | null;
}

interface Props {
  initData: string;
  onExit: () => void;
}

export default function ReadingScreen({ initData, onExit }: Props) {
  const [reading, setReading] = useState<ReadingState | null>(null);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [streamText, setStreamText] = useState('');
  const [error, setError] = useState('');
  const [synthesisText, setSynthesisText] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [reading, streamText, synthesisText, scrollToBottom]);

  const fetchState = useCallback(async (sessionId: string) => {
    try {
      const state = await apiGet<ReadingState>(
        `/api/v1/tarot/reading/state?session_id=${sessionId}`,
        initData,
      );
      setReading(state);
    } catch {
      setError('Не удалось загрузить состояние расклада.');
    }
  }, [initData]);

  const startReading = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await apiPost<{ session_id: string; state: string }>(
        '/api/v1/tarot/reading/start',
        {},
        initData,
      );
      await fetchState(data.session_id);
    } catch {
      setError('Не удалось начать расклад.');
    } finally {
      setLoading(false);
    }
  }, [initData, fetchState]);

  useEffect(() => {
    startReading();
  }, [startReading]);

  const handleAsk = async () => {
    if (!question.trim() || !reading || loading) return;
    setLoading(true);
    setError('');
    try {
      await apiPost(
        '/api/v1/tarot/reading/ask',
        { session_id: reading.session_id, question: question.trim() },
        initData,
      );
      setQuestion('');
      await fetchState(reading.session_id);
    } catch {
      setError('Не удалось задать вопрос.');
    } finally {
      setLoading(false);
    }
  };

  const handleDraw = async () => {
    if (!reading || loading) return;
    setLoading(true);
    setError('');
    try {
      await apiPost(
        '/api/v1/tarot/reading/draw',
        { session_id: reading.session_id },
        initData,
      );
      await fetchState(reading.session_id);
    } catch {
      setError('Не удалось вытянуть карту.');
    } finally {
      setLoading(false);
    }
  };

  const handleInterpret = async () => {
    if (!reading || loading) return;
    setLoading(true);
    setError('');
    setStreamText('');

    try {
      await apiStream(
        '/api/v1/tarot/reading/interpret',
        { session_id: reading.session_id },
        initData,
        (chunk) => {
          setStreamText((prev) => prev + chunk);
        },
        () => {
          setLoading(false);
          fetchState(reading.session_id);
        },
      );
    } catch {
      setError('Не удалось получить толкование.');
      setLoading(false);
    }
  };

  const handleSynthesis = async () => {
    if (!reading || loading) return;
    setLoading(true);
    setError('');
    setSynthesisText('');

    try {
      await apiStream(
        '/api/v1/tarot/reading/synthesis',
        { session_id: reading.session_id },
        initData,
        (chunk) => {
          setSynthesisText((prev) => prev + chunk);
        },
        () => {
          setLoading(false);
          fetchState(reading.session_id);
        },
      );
    } catch {
      setError('Не удалось получить синтез.');
      setLoading(false);
    }
  };

  const handleNewReading = async () => {
    setStreamText('');
    setSynthesisText('');
    setQuestion('');
    setError('');
    await startReading();
  };

  if (!reading && !error) {
    return (
      <div className="reading-screen">
        <div className="reading-loading">
          <span className="spinner" /> Загрузка...
        </div>
      </div>
    );
  }

  if (error && !reading) {
    return (
      <div className="reading-screen">
        <div className="error-msg">
          <p>{error}</p>
          <button onClick={handleNewReading}>Начать заново</button>
        </div>
      </div>
    );
  }

  if (!reading) return null;

  const progress = Math.round((reading.cycle_count / reading.max_cycles) * 100);

  return (
    <div className="reading-screen">
      {reading.cycles.length > 0 && (
        <div className="reading-history">
          <h3>Прошлые циклы</h3>
          {reading.cycles.map((cycle, i) => (
            <div key={i} className="history-cycle">
              <div className="history-cycle-header">
                <span className="cycle-number">Цикл {i + 1}</span>
                <div className="history-cards">
                  {cycle.cards.map((card, ci) => (
                    <img
                      key={ci}
                      src={getCardImage(card)}
                      alt={getCardName(card)}
                      className="history-card-thumb"
                    />
                  ))}
                </div>
              </div>
              <p className="history-question">{cycle.question}</p>
              <p className="history-answer">{cycle.answer}</p>
            </div>
          ))}
        </div>
      )}

      <div className="reading-current">
        <h2>Текущий цикл {reading.cycle_count + 1}/{reading.max_cycles}</h2>

        {reading.current_card && (
          <div className="current-card">
            <img
              src={getCardImage(reading.current_card)}
              alt={getCardName(reading.current_card)}
              className="current-card-image"
            />
            <p className="current-card-name">{getCardName(reading.current_card)}</p>
          </div>
        )}

        {reading.current_question && !reading.current_card && (
          <p className="current-question">Ваш вопрос: {reading.current_question}</p>
        )}

        {streamText && (
          <div className="interpretation-text">
            <p>{streamText}</p>
          </div>
        )}

        {synthesisText && (
          <div className="synthesis-text">
            <h3>Итоговая синтезация</h3>
            <p>{synthesisText}</p>
          </div>
        )}

        <div className="reading-actions">
          {reading.state === 'ОЖИДАНИЕ' && (
            <>
              <div className="input-row">
                <input
                  type="text"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="Задайте вопрос картам..."
                  disabled={loading}
                  onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
                />
                <button onClick={handleAsk} disabled={loading || !question.trim()}>
                  {loading ? '...' : '→'}
                </button>
              </div>
            </>
          )}

          {reading.state === 'ВОПРОС ЗАДАН' && (
            <button onClick={handleDraw} disabled={loading}>
              {loading ? <><span className="spinner" /> Вытягиваю...</> : 'Вытянуть карту'}
            </button>
          )}

          {reading.state === 'КАРТА ВЫТЯНУТА' && (
            <button onClick={handleInterpret} disabled={loading}>
              {loading ? <><span className="spinner" /> Толкую...</> : 'Получить толкование'}
            </button>
          )}

          {reading.state === 'ИНТЕРПРЕТАЦИЯ' && (
            <div className="reading-status">
              <span className="spinner" /> Толкование загружается...
            </div>
          )}

          {reading.state === 'ГОТОВО' && (
            <div className="cycle-complete-actions">
              {reading.cycle_count < reading.max_cycles && (
                <button onClick={() => fetchState(reading.session_id)} disabled={loading}>
                  Следующий цикл
                </button>
              )}
              <button onClick={handleSynthesis} disabled={loading} className="synthesis-btn">
                {loading ? <><span className="spinner" /> Синтезирую...</> : 'Синтезировать расклад'}
              </button>
            </div>
          )}

          {reading.state === 'ЗАВЕРШЕНО' && (
            <div className="reading-complete-actions">
              <button onClick={handleNewReading}>Новый расклад</button>
              <button onClick={onExit} className="exit-btn">На главную</button>
            </div>
          )}
        </div>

        {error && (
          <div className="error-msg">
            <p>{error}</p>
            <button onClick={() => setError('')}>Закрыть</button>
          </div>
        )}
      </div>

      <div className="reading-progress">
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
        <p className="progress-text">
          Цикл {reading.cycle_count} из {reading.max_cycles}
        </p>
      </div>

      <div ref={messagesEndRef} />
    </div>
  );
}
