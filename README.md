# Morlana: ИИ-Таролог

Telegram Mini App для персонализированных раскладов Таро с ИИ.

## Технологии

- **Frontend:** React 18 + TypeScript + Vite
- **Backend:** FastAPI (Python 3.12)
- **База данных:** PostgreSQL 14
- **ИИ:** MiMo LLM API (GPT-4o-mini для фри-тера, Claude/GPT-4o для премиума)

## Быстрый старт

### Через Docker (рекомендуется)

```bash
# 1. Скопируйте .env.example в .env и заполните секреты
cp .env.example .env

# 2. Запустите все сервисы
docker compose up --build

# 3. Откройте приложение
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# Health check: http://localhost:8000/health
```

### Локальная разработка

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # или venv\Scripts\activate на Windows
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `TELEGRAM_BOT_TOKEN` | Токен бота из @BotFather |
| `DATABASE_URL` | URL подключения к PostgreSQL |
| `LLM_API_KEY` | API ключ LLM провайдера |
| `LLM_BASE_URL` | Базовый URL API LLM |
| `PAYMENT_PROVIDER_TOKEN` | Токен платежной системы |
| `CORS_ORIGINS` | Разрешённые origins (через запятую) |

## Архитектура

```
backend/
├── main.py              # FastAPI entry point
├── config.py            # Pydantic settings
├── database.py          # SQLAlchemy async engine
├── logging_config.py    # Structured logging
├── models/              # ORM модели (User, TarotSession, ChatHistory)
├── routes/              # API роуты (astrology, tarot, sessions)
├── schemas/             # Pydantic схемы
└── services/            # Бизнес-логика (auth, llm, tarot, zodiac)

frontend/
├── src/
│   ├── App.tsx          # Root component + screen router
│   ├── api/client.ts    # HTTP + SSE клиент
│   ├── components/      # UI компоненты
│   ├── hooks/           # React хуки (useTelegram)
│   ├── styles/          # CSS
│   └── utils/           # Утилиты (cardMap)
└── public/              # Tarot card images (78 карт)
```

## API Endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Health check |
| POST | `/api/v1/astrology/bonus` | Онбординг + зодиакальный анализ |
| GET | `/api/v1/tarot/check-access` | Проверка подписки |
| POST | `/api/v1/tarot/draw` | Выбор карт |
| POST | `/api/v1/tarot/predict/stream` | SSE стриминг ответа ИИ |
| POST | `/api/v1/sessions/close` | Архивирование сессии |

## Лицензия

MIT
