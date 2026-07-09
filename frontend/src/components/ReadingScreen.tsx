import { useState, useEffect, useRef, useCallback } from 'react';
import { apiPost, apiGet, apiStream } from '../api/client';
import { getCardImage, getCardName } from '../utils/cardMap';
import '../styles/reading.css';

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
  onHistory?: () => void;
}

export default function ReadingScreen({ initData, onExit, onHistory }: Props) {
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
        (cleaned) => {
          setStreamText(cleaned);
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
        (cleaned) => {
          setSynthesisText(cleaned);
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

  const handleNextCycle = async () => {
    if (!reading || loading) return;
    setLoading(true);
    setError('');
    setStreamText('');
    try {
      await apiPost(
        '/api/v1/tarot/reading/next',
        { session_id: reading.session_id },
        initData,
      );
      await fetchState(reading.session_id);
    } catch {
      setError('Не удалось начать новый цикл.');
    } finally {
      setLoading(false);
    }
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
      {/* Card Container - 3/4 screen */}
      <div className="card-container">
        {reading.current_card ? (
          <div className="current-card">
            <img
              src={getCardImage(reading.current_card)}
              alt={getCardName(reading.current_card)}
              className="current-card-image"
            />
            <p className="current-card-name">{getCardName(reading.current_card)}</p>
          </div>
        ) : reading.current_question ? (
          <p className="current-question">Ваш вопрос: {reading.current_question}</p>
        ) : (
          <h2>Цикл {reading.cycle_count + 1}/{reading.max_cycles}</h2>
        )}
      </div>

      {/* Dots Indicator */}
      {reading.current_card && (
        <div className="dots-indicator">
          <div className="dot active" />
          <div className="dot" />
          <div className="dot" />
        </div>
      )}

      {/* Scrollable Interpretation */}
      {(streamText || synthesisText) && (
        <div className="interpretation-container">
          <div className="interpretation-gradient-top" />
          <div className="interpretation-scroll" ref={messagesEndRef}>
            {synthesisText && (
              <div className="synthesis-text">
                <h3>Итоговая синтезация</h3>
                <p>{synthesisText}</p>
              </div>
            )}
            {streamText && (
              <div className="interpretation-text">
                <p>{streamText}</p>
              </div>
            )}
          </div>
          <div className="interpretation-gradient-bottom" />
        </div>
      )}

      {/* Action Buttons */}
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

        {(reading.state === 'ГОТОВО' || reading.state === 'ЗАВЕРШЕНО') && (
          <div className="cycle-complete-actions">
            {reading.cycle_count < reading.max_cycles && reading.state === 'ГОТОВО' && (
              <button onClick={handleNextCycle} disabled={loading}>
                Следующий цикл
              </button>
            )}
            {!synthesisText && (
              <button onClick={handleSynthesis} disabled={loading} className="synthesis-btn">
                {loading ? <><span className="spinner" /> Синтезирую...</> : 'Синтезировать расклад'}
              </button>
            )}
          </div>
        )}

        {reading.state === 'ЗАВЕРШЕНО' && (
          <div className="reading-complete-actions">
            <button onClick={handleNewReading}>Новый расклад</button>
            <button onClick={onHistory}>Мои расклады</button>
            <button onClick={onExit} className="exit-btn">На главную</button>
          </div>
        )}
      </div>

      {/* Progress Bar */}
      <div className="reading-progress">
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
        <p className="progress-text">
          Цикл {reading.cycle_count} из {reading.max_cycles}
        </p>
      </div>

      {/* Error */}
      {error && (
        <div className="error-msg">
          <p>{error}</p>
          <button onClick={() => setError('')}>Закрыть</button>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
}
