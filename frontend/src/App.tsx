import { useState, useEffect } from 'react';
import { apiGet, ApiError } from './api/client';
import { useTelegram } from './hooks/useTelegram';
import Onboarding from './components/Onboarding';
import LoginScreen from './components/LoginScreen';
import UserDashboard from './components/UserDashboard';
import ReadingScreen from './components/ReadingScreen';
import ReadingHistory from './components/ReadingHistory';
import BottomNav from './components/BottomNav';

type Screen = 'login' | 'onboarding' | 'dashboard' | 'reading' | 'history';

interface AppState {
  screen: Screen;
  userLogin: string | null;
  userName: string | null;
}

const STORAGE_KEY = 'morlana_state';
/* Выставляется кнопкой «Выйти»: пока флаг стоит, автоматический вход не срабатывает
   и человек может войти под другим аккаунтом. Снимается успешным входом. */
const SIGNED_OUT_KEY = 'morlana_signed_out';

interface MeResponse {
  login: string;
  real_name: string;
}

function isSignedOut(): boolean {
  try {
    return localStorage.getItem(SIGNED_OUT_KEY) === '1';
  } catch {
    return false;
  }
}

function setSignedOut(value: boolean) {
  try {
    if (value) localStorage.setItem(SIGNED_OUT_KEY, '1');
    else localStorage.removeItem(SIGNED_OUT_KEY);
  } catch {
    // ignore
  }
}

const VALID_SCREENS: Screen[] = ['login', 'onboarding', 'dashboard', 'reading', 'history'];

/* Screens that only make sense for a logged-in user */
const AUTH_SCREENS: Screen[] = ['dashboard', 'reading', 'history'];

function loadState(): AppState | null {
  if (new URLSearchParams(window.location.search).get('reset') === '1') {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || !VALID_SCREENS.includes(parsed.screen)) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    const userLogin = typeof parsed.userLogin === 'string' ? parsed.userLogin : null;
    const userName = typeof parsed.userName === 'string' ? parsed.userName : null;
    const screen: Screen =
      AUTH_SCREENS.includes(parsed.screen) && !userLogin ? 'login' : parsed.screen;
    return { screen, userLogin, userName };
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

function saveState(state: AppState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore
  }
}

function App() {
  const { initData, photoUrl } = useTelegram();
  const [state, setState] = useState<AppState>(() => {
    const saved = loadState();
    return saved || { screen: 'login', userLogin: null, userName: null };
  });
  /* «Новый расклад» на главной начинает расклад с нуля, а вкладка «Расклад»
     в нижнем меню продолжает незаконченный. Флаг не сохраняется в localStorage. */
  const [freshReading, setFreshReading] = useState(false);

  useEffect(() => {
    saveState(state);
  }, [state]);

  /* Личность на сервере подтверждается подписью Telegram, поэтому логин и пароль
     при каждом запуске не нужны: спрашиваем сервер, есть ли аккаунт у этого
     Telegram-пользователя, и пускаем сразу. initData на первом рендере пуст. */
  useEffect(() => {
    if (!initData || state.userLogin || isSignedOut()) return;
    let cancelled = false;
    (async () => {
      try {
        const me = await apiGet<MeResponse>('/api/v1/auth/me', initData);
        if (cancelled) return;
        setState((prev) => ({
          screen: AUTH_SCREENS.includes(prev.screen) ? prev.screen : 'dashboard',
          userLogin: me.login,
          userName: me.real_name,
        }));
      } catch (err) {
        if (cancelled) return;
        /* 404 — у этого Telegram-аккаунта ещё нет учётной записи: регистрация.
           Остальные ошибки (нет сети, не Telegram) оставляют экран входа. */
        if (err instanceof ApiError && err.status === 404) {
          setState((prev) => (prev.screen === 'login' ? { ...prev, screen: 'onboarding' } : prev));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initData, state.userLogin]);

  const handleLogin = (data: { login: string; real_name: string }) => {
    setSignedOut(false);
    setState({ screen: 'dashboard', userLogin: data.login, userName: data.real_name });
  };

  const handleRegister = () => {
    setState((prev) => ({ ...prev, screen: 'onboarding' }));
  };

  const handleOnboardingComplete = (data: { login: string; real_name: string }) => {
    setSignedOut(false);
    setState({ screen: 'dashboard', userLogin: data.login, userName: data.real_name });
  };

  const handleLogout = () => {
    localStorage.removeItem(STORAGE_KEY);
    setSignedOut(true);
    setState({ screen: 'login', userLogin: null, userName: null });
  };

  const handleNavigate = (screen: 'home' | 'reading' | 'history') => {
    if (screen === 'home') {
      setState((prev) => ({ ...prev, screen: 'dashboard' }));
    } else if (screen === 'reading') {
      setFreshReading(false);
      setState((prev) => ({ ...prev, screen: 'reading' }));
    } else if (screen === 'history') {
      setState((prev) => ({ ...prev, screen: 'history' }));
    }
  };

  const handleNewReading = () => {
    setFreshReading(true);
    setState((prev) => ({ ...prev, screen: 'reading' }));
  };

  const handleExitReading = () => {
    setState((prev) => ({ ...prev, screen: 'dashboard' }));
  };

  const showNav = state.screen === 'dashboard' || state.screen === 'reading' || state.screen === 'history';
  const navScreen = state.screen === 'dashboard' ? 'home' : state.screen as 'reading' | 'history';

  return (
    <div className="app">
      <div className="app-content">
        {state.screen === 'login' && (
          <LoginScreen initData={initData} onLogin={handleLogin} onRegister={handleRegister} />
        )}

        {state.screen === 'onboarding' && (
          <Onboarding
            initData={initData}
            onComplete={handleOnboardingComplete}
            onBack={() => setState((prev) => ({ ...prev, screen: 'login' }))}
          />
        )}

        {state.screen === 'dashboard' && state.userLogin && (
          <UserDashboard
            initData={initData}
            photoUrl={photoUrl}
            userLogin={state.userLogin}
            onLogout={handleLogout}
            onNewReading={handleNewReading}
            onOpenHistory={() => handleNavigate('history')}
          />
        )}

        {state.screen === 'reading' && (
          <ReadingScreen
            initData={initData}
            onExit={handleExitReading}
            onHistory={() => handleNavigate('history')}
            startFresh={freshReading}
          />
        )}

        {state.screen === 'history' && (
          <ReadingHistory initData={initData} onBack={() => handleNavigate('home')} />
        )}
      </div>

      {showNav && (
        <BottomNav active={navScreen} onNavigate={handleNavigate} />
      )}
    </div>
  );
}

export default App;
