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
#    (одноразовый сервис migrate сам выполнит `alembic upgrade head`,
#    backend стартует только после его успешного завершения)
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
├── database.py          # SQLAlchemy async engine + проверка ревизии схемы
├── logging_config.py    # Structured logging
├── alembic/             # Миграции (единственный способ менять схему БД)
├── models/              # ORM модели (User, TarotSession, ReadingCycle)
├── routes/              # API роуты (astrology, auth, reading)
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
| POST | `/api/v1/auth/register` | Регистрация (логин + пароль, привязка к Telegram ID) |
| POST | `/api/v1/auth/login` | Вход |
| GET | `/api/v1/auth/me` | Текущий пользователь |
| POST | `/api/v1/tarot/reading/start` | Начать расклад |
| GET | `/api/v1/tarot/reading/active` | Незавершённый расклад пользователя |
| POST | `/api/v1/tarot/reading/ask` | Задать вопрос |
| POST | `/api/v1/tarot/reading/draw` | Вытянуть карту (RNG на бэкенде) |
| POST | `/api/v1/tarot/reading/interpret` | SSE стриминг толкования |
| POST | `/api/v1/tarot/reading/next` | Следующий цикл |
| POST | `/api/v1/tarot/reading/synthesis` | SSE стриминг итогового синтеза |
| GET | `/api/v1/tarot/reading/state` | Состояние расклада |
| GET | `/api/v1/tarot/reading/history` | История раскладов |

## Миграции

Схему БД меняет **только Alembic**. `Base.metadata.create_all()` из приложения удалён:
backend сам таблиц не создаёт и ничего в схеме не правит. При старте он сравнивает
`alembic_version.version_num` с head-ревизией из `backend/alembic/versions` и, если они
не совпадают (или таблицы `alembic_version` нет), отказывается запускаться:

```
RuntimeError: Database schema is at <x>, expected <head>. Run: alembic upgrade head
```

В `docker compose up` миграции применяет одноразовый сервис `migrate`
(`alembic upgrade head`); `backend` ждёт его успешного завершения.
URL базы Alembic всегда берёт из `DATABASE_URL` (как и приложение), а не из `alembic.ini`.

### Применить миграции

```bash
# Docker (стек уже поднят)
docker compose run --rm --no-deps migrate

# Локально
cd backend
alembic upgrade head
```

Полезное: `alembic current` — ревизия базы, `alembic history` — цепочка,
`alembic downgrade -1` — откат на один шаг.

### Создать миграцию

```bash
cd backend
# 1. Измените модели в models/ (индексы и ограничения — в __table_args__, с явными именами)
# 2. Сгенерируйте миграцию по разнице "модели <-> база" (база должна быть на head)
alembic revision --autogenerate -m "add something"
# 3. ПРОЧИТАЙТЕ и поправьте файл в alembic/versions/ — autogenerate не видит
#    переименований и не переносит данные; допишите downgrade()
# 4. Примените и убедитесь, что модели и база совпадают
alembic upgrade head
alembic check        # должно вывести "No new upgrade operations detected."
```

`alembic check` сравнивает таблицы, колонки, типы, nullable, server default, индексы и
unique-ограничения; он же выполняется в CI. В Docker любую из команд выше можно запустить так:
`docker compose run --rm --no-deps backend alembic <команда>` (чтобы файл новой ревизии
появился на хосте, добавьте `-v ./backend:/app`).

### База, созданная через create_all (нет таблицы alembic_version)

Старые версии приложения создавали таблицы сами, поэтому у такой базы нет таблицы
`alembic_version`, и `alembic upgrade head` упадёт с `relation "users" already exists`
(ничего не изменив — DDL в PostgreSQL транзакционный). Базу нужно один раз «усыновить»:

1. Сделайте бэкап: `docker compose exec -T db pg_dump -U user morlana_db > backup.sql`.
2. Посмотрите, что уже есть в базе (`\d users`, `\d tarot_sessions`, `\dt` в `psql`),
   и выберите **самую позднюю** ревизию, все объекты которой существуют:

   | Что есть в базе | Ревизия для `alembic stamp` |
   |-----------------|-----------------------------|
   | `users.login` и `users.password_hash` | `c1d2e3f4a5b6` |
   | нет `users.login`, но есть `tarot_sessions.synthesis`, `spread_name`, `updated_at` и `reading_cycles.card_name` | `b7c8d9e0f1a2` |
   | нет `tarot_sessions.synthesis`, но есть таблица `reading_cycles` и `tarot_sessions.cycle_count` | `a1b2c3d4e5f6` |
   | только `users`, `tarot_sessions`, `chat_histories` | `0647ca7d6717` |

   Колонки `users.gender` / `users.birth_location` при выборе **не учитываются**: их никогда
   не создавала ни одна миграция, и `d2e3f4a5b6c7` добавит их, только если их нет.
3. Проставьте ревизию и догоните до head:

   ```bash
   alembic stamp c1d2e3f4a5b6   # ревизия из таблицы
   alembic upgrade head
   alembic check
   ```

Никогда не ставьте `stamp` на `d2e3f4a5b6c7`, `e3f4a5b6c7d8` или `head`: эти миграции должны
реально выполниться. `d2e3f4a5b6c7` идемпотентна и приводит любую из линий (чистые миграции
или create_all) к одной схеме: добавляет недостающие колонки, выравнивает nullable и
server default, переименовывает `users_login_key` в `uq_users_login`, удаляет дубликаты
`(session_id, cycle_number)` в `reading_cycles` (остаётся запись с наибольшим `id`), создаёт
индекс `ix_tarot_sessions_user_status_created` и ограничение `uq_reading_cycles_session_cycle`.

Если `upgrade` падает с `already exists` уже после `stamp`, база в смешанном состоянии
(объект из более поздней ревизии уже создан вручную или через create_all). Упавшая миграция
откатывается целиком, так что можно спокойно: добавить руками недостающее из промежуточной
ревизии (см. её файл в `backend/alembic/versions`), сделать `alembic stamp` на неё и повторить
`alembic upgrade head`.

> **Внимание:** `e3f4a5b6c7d8` безвозвратно удаляет таблицу `chat_histories` (легаси-чат,
> эндпоинты `/api/v1/tarot/check-access`, `/draw`, `/predict/stream` и `/api/v1/sessions/close`
> удалены). `downgrade` воссоздаёт её пустой. Если данные нужны — выгрузите их заранее:
> `pg_dump -U user -t chat_histories morlana_db`.
>
> Если на уже мигрированной базе запустить сборку до `e3f4a5b6c7d8` (откат образа, рестарт
> старого контейнера), её `create_all` молча создаст пустую `chat_histories` заново. Новому
> backend это не мешает, `downgrade` её учитывает (`CREATE TABLE IF NOT EXISTS`), но
> `alembic check` покажет лишнюю таблицу — её можно просто удалить: `DROP TABLE chat_histories;`.

## Тесты

Тесты бэкенда лежат в `backend/tests` и ходят в приложение по HTTP (httpx поверх ASGI, с
настоящим lifespan), в настоящий PostgreSQL и настоящий Redis. Заглушка одна — LLM
(`routes.reading.stream_prediction`), сеть и ключ API не нужны.

### Запуск в Docker

Нужны запущенные контейнеры `db` и `redis` (обычный `docker compose up`). Команда ничего не
пересоздаёт и не трогает работающие `backend`/`frontend` (`--no-deps`), а dev-зависимости
ставит во временный контейнер, который удаляется после прогона:

```bash
docker compose build backend
docker compose run --rm --no-deps --user root -e DATABASE_URL=postgresql+psycopg://user:pass@db:5432/morlana_test -e REDIS_URL=redis://redis:6379/15 backend sh -c "pip install -q --root-user-action=ignore -r requirements-dev.txt && ruff check . && pytest -q"
```

Команда одинаково работает в PowerShell и в bash. `docker compose build backend` нужен, чтобы
в образ попал текущий код; чтобы гонять тесты по рабочему дереву без пересборки, добавьте
после `--user root` ключ `-v ./backend:/app` (ruff тогда оставит на хосте каталог
`backend/.ruff_cache` — git его не видит, в образ он не попадает).

### Что важно знать

- **Рабочая база не затрагивается.** `tests/conftest.py` выставляет окружение до импорта
  приложения: из `DATABASE_URL`/`REDIS_URL` берутся только хост и учётные данные, имя базы
  всегда заменяется на `morlana_test`, а Redis — на db `15`. Токен бота, `DEV_MODE`,
  `CORS_ORIGINS` и `LLM_API_KEY` тоже подменяются тестовыми, значения из `.env` игнорируются.
- База `morlana_test` создаётся сама. В начале прогона её схема `public` удаляется и
  строится заново командой `alembic upgrade head` (отдельным процессом) — то есть каждый
  прогон заодно проверяет всю цепочку миграций с нуля. Перед каждым тестом все таблицы
  очищаются (`TRUNCATE`), Redis db 15 — `FLUSHDB`.
- Telegram-подпись настоящая: `tests.helpers.sign_init_data(user_id, age_seconds=0)` подписывает
  initData тестовым токеном `123456:TEST` тем же HMAC, что и Telegram.
- Rate limit (slowapi) в тестах выключен, кроме одного теста с фикстурой `rate_limits_on`.
- Фикстура `llm` отдаёт фиксированные чанки; `llm.fail = True` — LLM, падающая посреди стрима.

Локально без Docker (нужны PostgreSQL и Redis на localhost):

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
pytest -q
```

`ruff` проверяет только ошибки (`E9`, `F`: синтаксис, неиспользуемые импорты, неопределённые
имена) — правил форматирования нет (`backend/ruff.toml`).

### CI

`.github/workflows/ci.yml` запускается на каждый `push` и `pull_request`:

- **backend** — Python 3.12, сервисы `postgres:14` и `redis:7`: `ruff check`, `alembic upgrade head`
  на пустой базе, `alembic check` (модели совпадают с миграциями), `pytest`;
- **frontend** — Node 20: `npm ci`, `npx tsc --noEmit`, `npm run build`.

## Лицензия

MIT
