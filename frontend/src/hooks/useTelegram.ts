import { useEffect, useState } from 'react';

interface TelegramWebApp {
  initData: string;
  version: string;
  ready: () => void;
  expand: () => void;
  close: () => void;
  isVersionAtLeast?: (version: string) => boolean;
  /* Цвет шапки Telegram над приложением (Bot API 6.1; hex — с 6.9). */
  setHeaderColor?: (color: string) => void;
  /* Цвет фона под приложением: виден при оттягивании экрана (6.1). */
  setBackgroundColor?: (color: string) => void;
  /* Цвет нижней панели Telegram под приложением (7.10). */
  setBottomBarColor?: (color: string) => void;
  openInvoice: (url: string, callback?: (status: string) => void) => void;
  MainButton: {
    text: string;
    show: () => void;
    hide: () => void;
    onClick: (callback: () => void) => void;
  };
}

/* Фон приложения: тот же цвет, что у body в global.css. Шапка и нижняя панель
   Telegram красятся в него же, иначе сверху и снизу видны чужие полосы. */
const APP_BACKGROUND = '#0a0612';

/* Старые клиенты Telegram не знают части методов, а setHeaderColor до версии 6.9
   принимает только 'bg_color' / 'secondary_bg_color', но не hex. Поэтому каждый
   вызов защищён проверкой: на старом клиенте просто остаётся как было. */
function paintChrome(app: TelegramWebApp) {
  const supports = (version: string) => app.isVersionAtLeast?.(version) ?? false;
  try {
    if (app.setHeaderColor) {
      app.setHeaderColor(supports('6.9') ? APP_BACKGROUND : 'bg_color');
    }
    app.setBackgroundColor?.(APP_BACKGROUND);
    if (supports('7.10')) {
      app.setBottomBarColor?.(APP_BACKGROUND);
    }
  } catch {
    // Цвет — украшение: если клиент ругнулся, приложение работает дальше.
  }
}

export function useTelegram() {
  const [webApp, setWebApp] = useState<TelegramWebApp | null>(null);

  useEffect(() => {
    const w = window as unknown as { Telegram?: { WebApp?: TelegramWebApp } };
    if (w.Telegram?.WebApp) {
      const app = w.Telegram.WebApp;
      app.ready();
      app.expand();
      paintChrome(app);
      setWebApp(app);
    }
  }, []);

  return {
    webApp,
    initData: webApp?.initData || '',
  };
}
