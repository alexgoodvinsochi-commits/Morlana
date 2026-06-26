import { useEffect, useState } from 'react';

interface TelegramWebApp {
  initData: string;
  ready: () => void;
  expand: () => void;
  close: () => void;
  openInvoice: (url: string, callback?: (status: string) => void) => void;
  MainButton: {
    text: string;
    show: () => void;
    hide: () => void;
    onClick: (callback: () => void) => void;
  };
}

export function useTelegram() {
  const [webApp, setWebApp] = useState<TelegramWebApp | null>(null);

  useEffect(() => {
    const w = window as unknown as { Telegram?: { WebApp?: TelegramWebApp } };
    if (w.Telegram?.WebApp) {
      const app = w.Telegram.WebApp;
      app.ready();
      app.expand();
      setWebApp(app);
    }
  }, []);

  return {
    webApp,
    initData: webApp?.initData || '',
  };
}
