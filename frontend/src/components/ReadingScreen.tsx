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

interface ActiveReading {
  session_id: string | null;
  state: string | null;
}

interface Props {
  initData: string;
  onExit: () => void;
  onHistory: () => void;
  /* Открыто кнопкой «Новый расклад»: начинаем с нуля, не продолжая прошлый. */
  startFresh?: boolean;
}

/* Толкование пишется на сервере даже без открытого стрима: пока состояние
   ИНТЕРПРЕТАЦИЯ, опрашиваем состояние, а после лимита предлагаем повтор. */
const INTERPRET_POLL_MS = 3000;
const INTERPRET_MAX_POLLS = 20;

export default function ReadingScreen({ initData, onExit, onHistory, startFresh = false }: Props) {
  const [reading, setReading] = useState<ReadingState | null>(null);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [streamText, setStreamText] = useState('');
  const [error, setError] = useState('');
  const [synthesisText, setSynthesisText] = useState('');
  const [interpretFailed, setInterpretFailed] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const interpretationRef = useRef<HTMLDivElement>(null);
  const isMountedRef = useRef(true);
  // Стрим толкования/синтеза идёт прямо сейчас — опрос состояния не нужен.
  const streamingRef = useRef(false);
  /* Сбрасывается только после успешного /start: первый рендер приходит с пустым
     initData, и та попытка не должна съедать запрос на новый расклад. */
  const startFreshRef = useRef(startFresh);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [reading, streamText, synthesisText]);

  useEffect(() => {
    const scroll = interpretationRef.current;
    if (scroll) {
      scroll.scrollTop = scroll.scrollHeight;
    }
  }, [streamText, synthesisText]);

  const fetchState = useCallback(async (sessionId: string): Promise<ReadingState | null> => {
    try {
      const state = await apiGet<ReadingState>(
        `/api/v1/tarot/reading/state?session_id=${sessionId}`,
        initData,
      );
      if (isMountedRef.current) {
        setReading(state);
      }
      return state;
    } catch {
      if (isMountedRef.current) {
        setError('Не удалось загрузить состояние расклада.');
      }
      return null;
    }
  }, [initData]);

  /* Ответ уже лежит в цикле на сервере (возврат на вкладку, фоновое толкование) —
     показываем его, если локальный стрим ничего не принёс. */
  const showLastAnswer = useCallback((state: ReadingState) => {
    const lastAnswer = state.cycles[state.cycles.length - 1]?.answer;
    if (lastAnswer && isMountedRef.current) {
      setStreamText((prev) => prev || lastAnswer);
    }
  }, []);

  const startReading = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await apiPost<{ session_id: string; state: string }>(
        '/api/v1/tarot/reading/start',
        {},
        initData,
      );
      if (!isMountedRef.current) return;
      await fetchState(data.session_id);
    } catch {
      if (isMountedRef.current) {
        setError('Не удалось начать расклад.');
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
    }
  }, [initData, fetchState]);

  /* Возврат на вкладку не теряет расклад: сначала спрашиваем у сервера,
     есть ли незавершённый, и только потом начинаем новый. */
  useEffect(() => {
    let cancelled = false;

    const resume = async () => {
      setLoading(true);
      setError('');
      try {
        if (!startFreshRef.current) {
          const active = await apiGet<ActiveReading>('/api/v1/tarot/reading/active', initData);
          if (cancelled) return;

          if (active.session_id) {
            const state = await fetchState(active.session_id);
            if (cancelled || !state) return;
            if (state.state === 'ГОТОВО' || state.state === 'ЗАВЕРШЕНО') {
              showLastAnswer(state);
            }
            return;
          }
        }

        const data = await apiPost<{ session_id: string; state: string }>(
          '/api/v1/tarot/reading/start',
          {},
          initData,
        );
        startFreshRef.current = false;
        if (cancelled) return;
        await fetchState(data.session_id);
      } catch {
        if (!cancelled && isMountedRef.current) {
          setError('Не удалось начать расклад.');
        }
      } finally {
        if (!cancelled && isMountedRef.current) {
          setLoading(false);
        }
      }
    };

    resume();

    return () => {
      cancelled = true;
    };
  }, [initData, fetchState, showLastAnswer]);

  /* Толкование могло уйти в фон (закрытая вкладка, оборванный стрим):
     подтягиваем состояние, пока сервер не допишет ответ. */
  useEffect(() => {
    const sessionId = reading?.session_id;
    if (!sessionId || reading?.state !== 'ИНТЕРПРЕТАЦИЯ') return;
    if (streamingRef.current || interpretFailed) return;

    let polls = 0;
    const timer = setInterval(async () => {
      polls += 1;
      if (polls > INTERPRET_MAX_POLLS) {
        clearInterval(timer);
        if (isMountedRef.current) {
          setInterpretFailed(true);
        }
        return;
      }
      const refreshed = await fetchState(sessionId);
      if (refreshed && refreshed.state !== 'ИНТЕРПРЕТАЦИЯ') {
        clearInterval(timer);
        showLastAnswer(refreshed);
      }
    }, INTERPRET_POLL_MS);

    return () => clearInterval(timer);
  }, [reading?.session_id, reading?.state, interpretFailed, fetchState, showLastAnswer]);

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
      if (!isMountedRef.current) return;
      setQuestion('');
      await fetchState(reading.session_id);
    } catch {
      if (isMountedRef.current) {
        setError('Не удалось задать вопрос.');
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
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
      if (!isMountedRef.current) return;
      await fetchState(reading.session_id);
    } catch {
      if (isMountedRef.current) {
        setError('Не удалось вытянуть карту.');
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
    }
  };

  const handleInterpret = async () => {
    if (!reading || loading) return;
    const sessionId = reading.session_id;
    setLoading(true);
    setError('');
    setInterpretFailed(false);
    setStreamText('');
    streamingRef.current = true;

    try {
      await apiStream(
        '/api/v1/tarot/reading/interpret',
        { session_id: sessionId },
        initData,
        (chunk) => {
          if (isMountedRef.current) {
            setStreamText((prev) => prev + chunk);
          }
        },
        () => {
          streamingRef.current = false;
          if (isMountedRef.current) {
            setLoading(false);
          }
          // Стрим мог оборваться без ответа — тогда состояние осталось ИНТЕРПРЕТАЦИЯ.
          fetchState(sessionId).then((refreshed) => {
            if (!isMountedRef.current || !refreshed) return;
            if (refreshed.state === 'ИНТЕРПРЕТАЦИЯ') {
              setError('Не удалось получить толкование.');
              setInterpretFailed(true);
            } else {
              showLastAnswer(refreshed);
            }
          });
        },
        (cleaned) => {
          if (isMountedRef.current) {
            setStreamText(cleaned);
          }
        },
      );
    } catch {
      streamingRef.current = false;
      if (isMountedRef.current) {
        setError('Не удалось получить толкование.');
        setInterpretFailed(true);
        setLoading(false);
      }
      fetchState(sessionId);
    }
  };

  const handleSynthesis = async () => {
    if (!reading || loading) return;
    const sessionId = reading.session_id;
    setLoading(true);
    setError('');
    setSynthesisText('');
    streamingRef.current = true;

    try {
      await apiStream(
        '/api/v1/tarot/reading/synthesis',
        { session_id: sessionId },
        initData,
        (chunk) => {
          if (isMountedRef.current) {
            setSynthesisText((prev) => prev + chunk);
          }
        },
        () => {
          streamingRef.current = false;
          if (isMountedRef.current) {
            setLoading(false);
          }
          fetchState(sessionId);
        },
        (cleaned) => {
          if (isMountedRef.current) {
            setSynthesisText(cleaned);
          }
        },
      );
    } catch {
      streamingRef.current = false;
      if (isMountedRef.current) {
        setError('Не удалось получить синтез.');
        setLoading(false);
      }
    }
  };

  const handleNewReading = async () => {
    if (loading) return;
    setStreamText('');
    setSynthesisText('');
    setQuestion('');
    setError('');
    setInterpretFailed(false);
    await startReading();
  };

  const handleNextCycle = async () => {
    if (!reading || loading) return;
    setLoading(true);
    setError('');
    setStreamText('');
    setInterpretFailed(false);
    try {
      await apiPost(
        '/api/v1/tarot/reading/next',
        { session_id: reading.session_id },
        initData,
      );
      if (!isMountedRef.current) return;
      await fetchState(reading.session_id);
    } catch {
      if (isMountedRef.current) {
        setError('Не удалось начать новый цикл.');
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
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
          <button onClick={handleNewReading} disabled={loading} aria-busy={loading}>
            Начать заново
          </button>
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
          <div className="interpretation-scroll" ref={interpretationRef}>
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
          <div className="input-row">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Задайте вопрос картам..."
              disabled={loading}
              onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
            />
            <button
              onClick={handleAsk}
              disabled={loading || !question.trim()}
              aria-busy={loading}
            >
              {loading ? '...' : '→'}
            </button>
          </div>
        )}

        {reading.state === 'ВОПРОС ЗАДАН' && (
          <button onClick={handleDraw} disabled={loading} aria-busy={loading}>
            {loading ? <><span className="spinner" /> Вытягиваю...</> : 'Вытянуть карту'}
          </button>
        )}

        {reading.state === 'КАРТА ВЫТЯНУТА' && (
          <button onClick={handleInterpret} disabled={loading} aria-busy={loading}>
            {loading ? <><span className="spinner" /> Толкую...</> : 'Получить толкование'}
          </button>
        )}

        {reading.state === 'ИНТЕРПРЕТАЦИЯ' && (
          interpretFailed ? (
            <div className="interpret-retry">
              {!error && <p className="reading-status">Толкование не пришло.</p>}
              <button onClick={handleInterpret} disabled={loading} aria-busy={loading}>
                {loading ? <><span className="spinner" /> Толкую...</> : 'Повторить толкование'}
              </button>
            </div>
          ) : (
            <div className="reading-status">
              <span className="spinner" /> Толкование загружается...
            </div>
          )
        )}

        {(reading.state === 'ГОТОВО' || reading.state === 'ЗАВЕРШЕНО') && (
          <div className="cycle-complete-actions">
            {reading.cycle_count < reading.max_cycles && reading.state === 'ГОТОВО' && (
              <button onClick={handleNextCycle} disabled={loading} aria-busy={loading}>
                Следующий цикл
              </button>
            )}
            {!synthesisText && (
              <button
                onClick={handleSynthesis}
                disabled={loading}
                aria-busy={loading}
                className="synthesis-btn"
              >
                {loading ? <><span className="spinner" /> Синтезирую...</> : 'Синтезировать расклад'}
              </button>
            )}
          </div>
        )}

        {reading.state === 'ЗАВЕРШЕНО' && (
          <div className="reading-complete-actions">
            <button onClick={handleNewReading} disabled={loading} aria-busy={loading}>
              Новый расклад
            </button>
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
