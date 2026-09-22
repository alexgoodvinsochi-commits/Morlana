# Morlana: ИИ-Таролог

Telegram Mini App для персонализированных раскладов Таро с ИИ.

Агентам и контрибьюторам: как работать в репозитории — `CLAUDE.md`, правила продукта — `instructions.md`.

## Технологии

- **Frontend:** React 18 + TypeScript + Vite
- **Backend:** FastAPI (Python 3.12)
- **База данных:** PostgreSQL 14; состояние расклада — Redis 7
- **ИИ:** OpenAI-совместимый провайдер MiMo через `AsyncOpenAI` (SDK `openai`). Модели задаются
  переменными `LLM_FREE_MODEL` (толкования без подписки и итоговый синтез) и `LLM_PREMIUM_MODEL`
  (толкования при активной подписке)

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

На хостах, где Python не может запустить async SQLAlchemy (например, Windows с политикой
Application Control), команды backend выполняйте в Docker — см. `CLAUDE.md`.

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

Backend читает их из `.env` (`backend/config.py`); шаблон — `.env.example`. В `docker compose`
для `migrate` и `backend` переменные `DATABASE_URL` и `REDIS_URL` переопределяются на сервисы
`db` и `redis`, остальные берутся из корневого `.env`.

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `TELEGRAM_BOT_TOKEN` | Токен бота из @BotFather; ключ проверки подписи initData. Пусто — любой подписанный initData отклоняется | пусто |
| `DATABASE_URL` | URL PostgreSQL, только драйвер psycopg 3 (`postgresql+psycopg://`). Его же берёт Alembic | `postgresql+psycopg://user:pass@localhost:5432/morlana_db` |
| `REDIS_URL` | URL Redis: состояние незавершённого расклада | `redis://localhost:6379/0` |
| `LLM_API_KEY` | Ключ OpenAI-совместимого провайдера. Пусто — вместо ответа LLM приходит заглушка «Модуль ИИ не настроен» | пусто |
| `LLM_BASE_URL` | Базовый URL API провайдера. Пусто — адрес OpenAI по умолчанию | пусто |
| `LLM_FREE_MODEL` | Модель толкований без подписки и итогового синтеза | `mimo-v2-flash` |
| `LLM_PREMIUM_MODEL` | Модель толкований при активной подписке (`subscription_ends_at` в будущем) | `mimo-v2-flash` |
| `CORS_ORIGINS` | Разрешённые origins через запятую, **без пробелов** (строка делится по запятой без обрезки) | `http://localhost:3000` |
| `DEV_MODE` | Только для локальной разработки: запрос без подписи Telegram считается одним фиксированным dev-аккаунтом; подпись, если она есть, проверяется всё равно. Backend не стартует, если при `DEV_MODE=true` в `CORS_ORIGINS` есть адрес не с `localhost`/`127.0.0.1` (например, ngrok) | `false` |
| `INIT_DATA_MAX_AGE` | Сколько секунд действует initData (по `auth_date`) | `86400` |
| `HISTORY_LIMIT_FREE` | Сколько архивных раскладов отдаёт `/history` без подписки. Из базы ничего не удаляется | `3` |
| `HISTORY_LIMIT_PREMIUM` | То же при активной подписке | `50` |
| `PAYMENT_PROVIDER_TOKEN` | Токен Telegram Payments. Пока не используется: роут оплаты не подключён | пусто |
| `SKIP_ONBOARDING` | Не используется: объявлена в `config.py`, код её не читает | `true` |

Колонка «По умолчанию» — значения из `config.py`. В `.env.example` для моделей стоят другие имена:
`mimo-v2.5` и `mimo-v2.5-pro`.

Фронтенд: `VITE_API_URL` (`frontend/.env.example`) — адрес API для `npm run dev`; в сборке для
nginx он пустой, запросы идут на тот же origin. Build-аргумент `VITE_SKIP_ONBOARDING`
(`frontend/Dockerfile`, `docker-compose.yml`) не используется: исходники его не читают.

## Архитектура

```
.github/workflows/
└── ci.yml               # CI: ruff, миграции на пустой базе, pytest, сборка фронтенда

backend/
├── main.py              # FastAPI entry point
├── config.py            # Pydantic settings
├── database.py          # SQLAlchemy async engine + проверка ревизии схемы
├── logging_config.py    # Structured logging
├── rate_limiter.py      # slowapi: лимиты на /auth, IP клиента из X-Forwarded-For
├── alembic/             # Миграции (единственный способ менять схему БД)
├── models/              # ORM модели (User, TarotSession, ReadingCycle)
├── prompts/             # Персона (persona.md) и конфиги раскладов (spreads/*.json)
├── routes/              # API роуты (astrology, auth, reading; payments не подключён)
├── schemas/             # Pydantic схемы
├── services/            # Бизнес-логика (auth, llm, password, reading, redis, tarot, zodiac)
└── tests/               # pytest: настоящие PostgreSQL и Redis, LLM заглушен

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
| POST | `/api/v1/astrology/bonus` | Профиль и знак зодиака по дате рождения, шаблонное приветствие (интерфейс не вызывает) |
| POST | `/api/v1/auth/register` | Регистрация (логин + пароль, привязка к Telegram ID) |
| POST | `/api/v1/auth/login` | Вход |
| GET | `/api/v1/auth/me` | Текущий пользователь |
| POST | `/api/v1/tarot/reading/start` | Начать расклад |
| GET | `/api/v1/tarot/reading/active` | Незавершённый расклад пользователя |
| POST | `/api/v1/tarot/reading/ask` | Задать вопрос |
| POST | `/api/v1/tarot/reading/draw` | Вытянуть карту (RNG на бэкенде) |
| POST | `/api/v1/tarot/reading/interpret` | SSE стриминг толкования |
| POST | `/api/v1/tarot/reading/next` | Следующий цикл |
| POST | `/api/v1/tarot/reading/synthesis` | Итоговый синтез: ответ LLM сначала сохраняется целиком, затем отдаётся по SSE чанками; сбой LLM — 502 |
| GET | `/api/v1/tarot/reading/state` | Состояние расклада |
| GET | `/api/v1/tarot/reading/history` | История раскладов (по умолчанию последние 3 без подписки, 50 с подпиской) |

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
появился на хосте, добавьте `-v ./backend:/app`; в Git Bash на Windows такую команду запускайте
с префиксом `MSYS_NO_PATHCONV=1`, иначе путь тома будет переписан).

### База, созданная через create_all (нет таблицы alembic_version)

Старые версии приложения создавали таблицы сами, поэтому у такой базы нет таблицы
`alembic_version`, и `alembic upgrade head` упадёт с `relation "users" already exists`
(ничего не изменив — DDL в PostgreSQL транзакционный). Базу нужно один раз «усыновить»:

1. Сделайте бэкап и положите его вне репозитория: в дампе данные пользователей, а `.gitignore`
   его не закрывает. Дамп снимается внутри контейнера и копируется наружу файлом, минуя
   перенаправление `>` (в PowerShell 5.1 оно портит дамп):

   ```bash
   docker compose exec -T db pg_dump -U user -Fc -f /tmp/morlana_db.dump morlana_db
   docker compose exec -T db pg_restore -l /tmp/morlana_db.dump
   docker compose cp db:/tmp/morlana_db.dump <папка вне репозитория>/morlana_db.dump
   docker compose exec -T db rm -f /tmp/morlana_db.dump
   ```

   `pg_restore -l` должен перечислить `TABLE DATA` для `users`, `tarot_sessions`,
   `reading_cycles` и `alembic_version`, иначе дамп неполный. В Git Bash ставьте перед каждой
   командой `MSYS_NO_PATHCONV=1` (иначе `/tmp` превратится в путь Windows и `pg_dump` упадёт),
   а папку назначения пишите в виде `C:/Users/<имя>/morlana-backups`.
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
> удалены). `downgrade` воссоздаёт её пустой. Если данные нужны — выгрузите их заранее тем же
> способом, что в шаге 1 выше, добавив к `pg_dump` ключ `-t chat_histories`.
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
`backend/.ruff_cache` — git его не видит, в образ он не попадает). Вариант с `-v` в Git Bash на
Windows запускайте с префиксом `MSYS_NO_PATHCONV=1`, иначе путь тома будет переписан.

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

Локально без Docker (нужны PostgreSQL и Redis на localhost; там, где async SQLAlchemy на хосте не
запускается, — только в Docker, см. выше):

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
pytest -q
```

`ruff` проверяет только ошибки (`E9`, `F`: синтаксис, неиспользуемые импорты, неопределённые
имена) — правил форматирования нет (`backend/ruff.toml`).

### CI

`.github/workflows/ci.yml` запускается на каждый `push` и `pull_request`. Оба job идут на
`ubuntu-24.04`: метка закреплена, чтобы переезд `ubuntu-latest` на Ubuntu 26 (с 19 октября 2026)
не поменял окружение незаметно.

- **backend** — Python 3.12, сервисы `postgres:14` и `redis:7`: `ruff check`, `alembic upgrade head`
  на пустой базе, `alembic check` (модели совпадают с миграциями), `pytest`;
- **frontend** — Node 20: `npm ci`, `npx tsc --noEmit`, `npm run build`.

## Лицензия

MIT
