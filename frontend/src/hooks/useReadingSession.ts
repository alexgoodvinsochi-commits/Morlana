import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, apiGet, apiPost, apiStream } from '../api/client';
import type { ReadingActiveResponse, ReadingStateResponse } from '../api/client';

/* Толкование пишется на сервере даже без открытого стрима: пока состояние
   INTERPRETATION, опрашиваем состояние, а после лимита предлагаем повтор. */
const INTERPRET_POLL_MS = 3000;
const INTERPRET_MAX_POLLS = 20;

export interface ReadingSession {
  reading: ReadingStateResponse | null;
  loading: boolean;
  error: string;
  streamText: string;
  synthesisText: string;
  /* Толкование не пришло: экран показывает кнопку повтора вместо ожидания. */
  interpretFailed: boolean;
  /* Действия-запросы возвращают true, если сервер их принял. */
  ask: (question: string) => Promise<boolean>;
  draw: () => Promise<boolean>;
  nextCycle: () => Promise<boolean>;
  restart: () => Promise<boolean>;
  /* Стримы: результат приходит в streamText и synthesisText. */
  interpret: () => Promise<void>;
  synthesize: () => Promise<void>;
  dismissError: () => void;
}

function describeError(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    if (e.status === 404) return 'Расклад не найден. Начните новый.';
    if (e.status === 409) return 'Расклад уже перешёл в другое состояние.';
    if (e.status === 429) return 'Слишком много запросов. Подождите немного.';
  }
  return fallback;
}

/* Весь жизненный цикл расклада: возобновление, запросы, стримы и опрос.
   Экран остаётся представлением и знает только то, что здесь возвращается. */
export function useReadingSession(initData: string, startFresh = false): ReadingSession {
  const [reading, setReading] = useState<ReadingStateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [streamText, setStreamText] = useState('');
  const [synthesisText, setSynthesisText] = useState('');
  const [interpretFailed, setInterpretFailed] = useState(false);

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

  const fetchState = useCallback(async (sessionId: string): Promise<ReadingStateResponse | null> => {
    try {
      const state = await apiGet<ReadingStateResponse>(
        `/api/v1/tarot/reading/state?session_id=${sessionId}`,
        initData,
      );
      if (isMountedRef.current) {
        setReading(state);
      }
      return state;
    } catch (e) {
      if (isMountedRef.current) {
        setError(describeError(e, 'Не удалось загрузить состояние расклада.'));
      }
      return null;
    }
  }, [initData]);

  /* Ответ уже лежит в цикле на сервере (возврат на вкладку, фоновое толкование) —
     показываем его, если локальный стрим ничего не принёс. */
  const showLastAnswer = useCallback((state: ReadingStateResponse) => {
    const lastAnswer = state.cycles[state.cycles.length - 1]?.answer;
    if (lastAnswer && isMountedRef.current) {
      setStreamText((prev) => prev || lastAnswer);
    }
  }, []);

  /* Действия расклада отвечают состоянием целиком: один запрос на действие. */
  const post = useCallback(async (
    path: string,
    body: Record<string, unknown>,
    fallback: string,
  ): Promise<boolean> => {
    setLoading(true);
    setError('');
    try {
      const state = await apiPost<ReadingStateResponse>(path, body, initData);
      if (!isMountedRef.current) return false;
      setReading(state);
      return true;
    } catch (e) {
      if (isMountedRef.current) {
        setError(describeError(e, fallback));
      }
      return false;
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
    }
  }, [initData]);

  /* Возврат на вкладку не теряет расклад: сначала спрашиваем у сервера,
     есть ли незавершённый, и только потом начинаем новый. */
  useEffect(() => {
    let cancelled = false;

    const resume = async () => {
      setLoading(true);
      setError('');
      try {
        if (!startFreshRef.current) {
          const active = await apiGet<ReadingActiveResponse>(
            '/api/v1/tarot/reading/active',
            initData,
          );
          if (cancelled) return;

          if (active.session_id) {
            const state = await fetchState(active.session_id);
            if (cancelled || !state) return;
            if (state.state === 'READY' || state.state === 'COMPLETED') {
              showLastAnswer(state);
            }
            return;
          }
        }

        const state = await apiPost<ReadingStateResponse>(
          '/api/v1/tarot/reading/start',
          {},
          initData,
        );
        startFreshRef.current = false;
        if (cancelled) return;
        if (isMountedRef.current) {
          setReading(state);
        }
      } catch (e) {
        if (!cancelled && isMountedRef.current) {
          setError(describeError(e, 'Не удалось начать расклад.'));
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
    if (!sessionId || reading?.state !== 'INTERPRETATION') return;
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
      if (refreshed && refreshed.state !== 'INTERPRETATION') {
        clearInterval(timer);
        showLastAnswer(refreshed);
      }
    }, INTERPRET_POLL_MS);

    return () => clearInterval(timer);
  }, [reading?.session_id, reading?.state, interpretFailed, fetchState, showLastAnswer]);

  const ask = useCallback(async (question: string): Promise<boolean> => {
    const text = question.trim();
    if (!reading || loading || !text) return false;
    return post(
      '/api/v1/tarot/reading/ask',
      { session_id: reading.session_id, question: text },
      'Не удалось задать вопрос.',
    );
  }, [reading, loading, post]);

  const draw = useCallback(async (): Promise<boolean> => {
    if (!reading || loading) return false;
    return post(
      '/api/v1/tarot/reading/draw',
      { session_id: reading.session_id },
      'Не удалось вытянуть карту.',
    );
  }, [reading, loading, post]);

  const nextCycle = useCallback(async (): Promise<boolean> => {
    if (!reading || loading) return false;
    setStreamText('');
    setInterpretFailed(false);
    return post(
      '/api/v1/tarot/reading/next',
      { session_id: reading.session_id },
      'Не удалось начать новый цикл.',
    );
  }, [reading, loading, post]);

  const restart = useCallback(async (): Promise<boolean> => {
    if (loading) return false;
    setStreamText('');
    setSynthesisText('');
    setInterpretFailed(false);
    return post('/api/v1/tarot/reading/start', {}, 'Не удалось начать расклад.');
  }, [loading, post]);

  const interpret = useCallback(async (): Promise<void> => {
    if (!reading || loading) return;
    const sessionId = reading.session_id;
    const cyclesBefore = reading.cycle_count;
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
          // Стрим мог оборваться без ответа — тогда состояние осталось INTERPRETATION.
          fetchState(sessionId).then((refreshed) => {
            if (!isMountedRef.current || !refreshed) return;
            if (refreshed.state === 'INTERPRETATION') {
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
    } catch (e) {
      streamingRef.current = false;
      if (isMountedRef.current) {
        setError(describeError(e, 'Не удалось получить толкование.'));
        setInterpretFailed(true);
        setLoading(false);
      }
      /* Стрим мог оборваться уже после того, как сервер дописал и сохранил
         толкование (свёрнутый Telegram, потеря связи). Тогда цикл засчитан:
         показываем целый ответ вместо оборванного куска и снимаем ошибку. */
      fetchState(sessionId).then((refreshed) => {
        if (!isMountedRef.current || !refreshed) return;
        if (refreshed.cycle_count <= cyclesBefore) return;
        const answer = refreshed.cycles[refreshed.cycles.length - 1]?.answer;
        if (!answer) return;
        setStreamText(answer);
        setError('');
        setInterpretFailed(false);
      });
    }
  }, [reading, loading, initData, fetchState, showLastAnswer]);

  const synthesize = useCallback(async (): Promise<void> => {
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
    } catch (e) {
      streamingRef.current = false;
      if (isMountedRef.current) {
        setError(describeError(e, 'Не удалось получить синтез.'));
        setLoading(false);
      }
      /* Сервер переводит расклад в COMPLETED до вызова LLM, поэтому после
         сбоя синтеза «Следующий цикл» на экране уже невозможен: перечитываем
         состояние, чтобы не предлагать кнопку, на которую придёт 409. */
      fetchState(sessionId);
    }
  }, [reading, loading, initData, fetchState]);

  const dismissError = useCallback(() => setError(''), []);

  return {
    reading,
    loading,
    error,
    streamText,
    synthesisText,
    interpretFailed,
    ask,
    draw,
    nextCycle,
    restart,
    interpret,
    synthesize,
    dismissError,
  };
}
