# CLAUDE.md

Morlana — Telegram Mini App «ИИ-Таролог»: пользователь задаёт вопрос, сервер тянет карту Таро, LLM стримит толкование; до 6 циклов в раскладе, затем синтез и архив в историю. Интерфейс на русском.

- `backend/`: Python 3.12, FastAPI 0.115, SQLAlchemy 2 async + psycopg 3 (не asyncpg), Postgres 14, Redis 7, Alembic, slowapi, LLM через `AsyncOpenAI` у OpenAI-совместимого провайдера: MiMo или Yandex AI Studio, выбор только переменными `LLM_*` (задача 11).
- `frontend/`: React 18 + TypeScript strict + Vite, без роутера, стейт-библиотек и CSS-фреймворков. В compose его отдаёт nginx на `:3000` и проксирует `/api/` на `backend:8000`.

Здесь только то, что не видно из кода за минуту. Остальное не дублируй, а ссылайся:

- `README.md` — запуск, переменные окружения, эндпоинты, миграции и `alembic stamp`, устройство тестов, CI.
- `instructions.md` — продукт: словарь, путь пользователя, состояния, бизнес-правила, известные пробелы, порядок этапов. Читай перед любой новой функциональностью.
- `docs/DESIGN.md` — оформление экрана расклада. `docs/ROADMAP.md` — порядок этапов с коммитами и бэклог (статус сверен с кодом 22.09.2026).

При расхождении документа с кодом прав код. Нашёл расхождение — сообщи владельцу, а не подгоняй молча одно под другое.

## Договорённости с владельцем

- Отвечай по-русски. Код, комментарии, логи, `detail` ошибок, commit messages — английский. Тексты UI и промпты LLM — русский.
- Спроси разрешения ДО: `git push`; запуска ngrok или `start.ps1` (приложение становится публичным); правки `.env`; любого изменения базы `morlana_db`, включая запуск стека с новой миграцией в дереве; перезапуска или остановки работающего стека (в том числе `up --build`); удаления данных.
- Заметные изменения (документы, контракты, архитектура) сначала показывай планом или черновиком на утверждение.
- `.env` не читать и не печатать. Имена переменных — в `backend/config.py` и `.env.example`. То же для `C:\Users\user\morlana-secrets\` (там ключ Yandex AI Studio; вне репозитория, потому что репозиторий на GitHub публичный): не читать, не копировать, в контейнер — только `docker run --env-file <файл>`.
- Правки хирургические: не рефактори соседний код заодно. Форматтера нет — не переформатируй файлы целиком. Мёртвый код (список в конце) не оживляй и не удаляй без запроса.
- Не забегай вперёд: задачи следующего этапа не делаются «по пути». Порядок этапов — в `instructions.md` (раздел 8) и `docs/ROADMAP.md`.

## Инварианты, которые нельзя ломать

Личность и доступ

1. Личность на backend — только проверенный Telegram `initData` из заголовка `Authorization: Bearer <initData>`. Ни один эндпоинт не доверяет `telegram_id` или логину из тела запроса. Логин и пароль — второй фактор того же Telegram-аккаунта; неверный логин, неверный пароль и чужой Telegram-аккаунт отвечают одинаковым 401 `Invalid login or password`.
2. `validate_telegram_init_data` (`services/auth.py`) не ослаблять: подпись проверяется всегда, когда есть `hash`, в том числе при `DEV_MODE`; пустой `TELEGRAM_BOT_TOKEN` означает отказ; `auth_date` не старше `INIT_DATA_MAX_AGE` (86400 с). `DEV_MODE` не отключает HMAC и не даёт выбрать личность: при `DEV_MODE=true` запрос без `hash` всегда становится одним фиксированным dev-аккаунтом, при `false` получает 401.
3. Чужой, несуществующий и некорректный `session_id` дают одинаковый 404 `Reading not found` (`_get_owned_session`). Не вводи 403: он раскрывает существование чужих раскладов.
4. Загрузочные проверки в `main.py` (DEV_MODE с не-локальным origin в `CORS_ORIGINS`; ревизия схемы) не обходить. 401 в обычном браузере при `DEV_MODE=false` — норма; не «чини» его включением DEV_MODE.
5. Карту выбирает только сервер; клиент никогда не присылает id карты. Флаг «вошёл» на фронтенде — это `localStorage`, не граница безопасности.
6. Пароли: scrypt (`services/password.py`), вызовы идут через `run_in_threadpool` в `routes/auth.py`; старые `salt:sha256` проверяются и перехешируются при входе. Этот путь не удалять.
7. Секреты только через `.env`. В логи не попадают `initData`, пароли и токен бота (httpx и httpcore приглушены до WARNING, потому что URL Bot API содержит токен).

Данные и миграции

8. Схему меняет только Alembic: `create_all` удалён, backend не стартует, если база не на head. Ревизию, уже применённую к базе владельца, не редактируй — пиши новую; к `morlana_db` применена вся цепочка по `e3f4a5b6c7d8` включительно (`d2e3f4a5b6c7` и `e3f4a5b6c7d8` — 22.09.2026). Никогда не делай `alembic stamp` вместо выполнения миграции (README запрещает stamp на `d2e3f4a5b6c7`, `e3f4a5b6c7d8` и `head`).
9. `morlana_db` в volume `pgdata` — реальные данные владельца: любое изменение только с разрешения и после `pg_dump` (задача 4). `docker compose up` и `start.ps1` сами запускают сервис `migrate`: «новая миграция + обычный запуск» уже меняет его базу. `docker compose down -v` и удаление volume запрещены. Дампы лежат в `C:\Users\user\morlana-backups`, вне репозитория: в них данные пользователей, а `.gitignore` не закрывает ни `*.sql`, ни `*.dump`.
10. Эксперименты — только на временных базах. Тесты работают в `morlana_test` (тот же контейнер Postgres, что и `morlana_db`) и в Redis db 15; проверки имени базы и номера Redis db в `tests/conftest.py` не ослаблять.
11. Архивные расклады не удаляются никогда; лимит истории (`HISTORY_LIMIT_FREE` = 3, `HISTORY_LIMIT_PREMIUM` = 50) применяется только при чтении. `/start` удаляет лишь пустые просроченные активные сессии.
12. В генераторе `/interpret` порядок записи фиксирован: commit в Postgres -> `cycle_data` в Redis -> переход состояния последним, чтобы сбой БД не оставил расклад в `ГОТОВО` без сохранённого цикла. Любая ошибка оставляет `ИНТЕРПРЕТАЦИЯ`, откуда `/interpret` повторяется. Если строка цикла уже закоммичена, а сбой случился позже, повтор завершает цикл из сохранённой строки без нового вызова LLM: вторая вставка нарушила бы `uq_reading_cycles_session_cycle`.

LLM: расход и кризисные сообщения

13. Квот нет: `users.free_requests_left` не проверяется и не уменьшается, на эндпоинтах расклада нет rate limit, длина вопроса не ограничена. Каждый `/interpret` и `/synthesis` — платный вызов провайдера: не гоняй их скриптами и циклами по живому стеку, для проверки хватает одного ручного вызова с согласия владельца. Тесты к провайдеру не ходят никогда (фикстура `llm` подменяет `routes.reading.stream_prediction`, а `test_llm_client.py` гоняет настоящий `stream_prediction` через `httpx.MockTransport`). Квоты — этап 3, точечно раньше не вводи.
14. Кризисные сообщения распознаёт сервер, детерминированно и до LLM (`services/safety.py`): если вопрос цикла кризисный (`is_crisis_message`), `/interpret` не зовёт LLM и отдаёт `CRISIS_REPLY` тем же путём, что обычный ответ (те же SSE-события, порядок записи из инварианта 12, цикл засчитывается), а `/synthesis` делает `CRISIS_REPLY` синтезом, если такой вопрос есть хоть в одном цикле. Правило в `persona.md` — только второй слой: `aliceai-llm-flash` его не выполнила. Не переноси проверку в промпт и не ставь её после вызова LLM; в лог идёт `session_id`, но не текст вопроса. Спорные фразы и принятые решения — комментарий в модуле; номера телефонов в `CRISIS_REPLY` и `persona.md` совпадают, это проверяет `test_safety.py`.

Парные контракты: ломаются молча, меняй обе стороны в одном коммите

- Значения состояний — русские строки (`ОЖИДАНИЕ`, `ВОПРОС ЗАДАН`, `КАРТА ВЫТЯНУТА`, `ИНТЕРПРЕТАЦИЯ`, `ГОТОВО`, `ЗАВЕРШЕНО`): `ReadingState` в `services/reading.py`, литералы в `frontend/src/components/ReadingScreen.tsx` и константы в `backend/tests/test_reading.py`.
- Карты 1..78: `get_card_name` в `services/llm.py` и `frontend/src/utils/cardMap.ts`. 1-22 старшие арканы (`maj00..maj21.jpg`), далее по 14 карт в порядке cups, pents, swords, wands.
- Английские `detail`, которые UI сравнивает буквально: `Invalid login or password`, `Login already taken`.
- SSE: `data: {"text": ...}` много раз, затем `{"cleaned": ...}`, затем `[DONE]`; при сбое `/interpret` вместо `cleaned` идёт `{"error": "interpretation_failed"}`. Стороны: `routes/reading.py` и `apiStream` в `frontend/src/api/client.ts`.

## Задачи

### 1. Запустить и остановить

```powershell
docker compose up --build -d   # db, redis, migrate (one-shot: alembic upgrade head НА morlana_db), backend :8000, frontend :3000
.\start.ps1                    # Docker Desktop + то же + health-check + проверка VPN + ngrok http 3000 (публично!)
.\stop.ps1                     # docker compose down + остановка ngrok; запускать из корня репозитория
docker compose logs -f backend
```

- `start.ps1` выходит с ошибкой при выключенном VPN (ngrok не принимает домашний IP владельца), но уже после `docker compose up --build -d`: стек к этому моменту пересобран и перезапущен.
- Код в контейнерах берётся из образа (нет bind mount и `--reload`). Правка видна в приложении только после пересборки, а это перезапуск стека: нужно разрешение.
- Backend не стартует, если база не на head (`Database schema is at <x>, expected <head>...`) или сработала проверка DEV_MODE (инвариант 4). По словам владельца, в его `.env` стоит `DEV_MODE=false`: приложение работает только внутри Telegram.
- `CORS_ORIGINS` — через запятую без пробелов (строка режется без trim). Проверка живости: `GET http://localhost:8000/health`.

### 2. Выполнить backend-команду: только в Docker

Python на хосте не запускает async SQLAlchemy (greenlet блокирует политика Application Control). Alembic, pytest, ruff и любые скрипты backend идут в контейнере; venv-рецепты из README на этой машине не работают.

```powershell
docker compose run --rm --no-deps backend <cmd>                      # код из образа morlana-backend
docker compose run --rm --no-deps -v ./backend:/app backend <cmd>    # код из рабочего дерева
docker compose run --rm --no-deps --user root backend sh -c "pip install ... && <cmd>"   # образ работает под appuser
```

- Без `-v` контейнер видит код на момент последней сборки образа, а не твои правки. `--no-deps` обязателен: без него `run backend` поднимет зависимости, в том числе `migrate` на `morlana_db`.
- Bash-инструмент на этой машине — Git Bash: он переписывает в аргументах всё, что похоже на Unix-путь (`./backend:/app` -> `.\backend;C:\Program Files\Git\app`, `/tmp/x.dump` -> `C:/Users/user/AppData/Local/Temp/x.dump`). Поэтому любую docker-команду с путём внутри контейнера запускай через PowerShell, а в Git Bash ставь префикс `MSYS_NO_PATHCONV=1`; это касается не только `-v`, но и `pg_dump -f /tmp/...` и подобного.

### 3. Прогнать тесты и линтер

```powershell
docker compose build backend   # свежий код в образ, работающие контейнеры не трогает; либо добавь `-v ./backend:/app` после `--user root`
docker compose run --rm --no-deps --user root -e DATABASE_URL=postgresql+psycopg://user:pass@db:5432/morlana_test -e REDIS_URL=redis://redis:6379/15 backend sh -c "pip install -q --root-user-action=ignore -r requirements-dev.txt && ruff check . && pytest -q"
cd frontend; npm run build     # tsc + vite build — единственная проверка фронтенда (lint и тестов нет)
```

- Нужны поднятые `db` и `redis`; работающие `backend` и `frontend` команда не трогает. Прогон занимает 1-2 минуты вместе с установкой dev-зависимостей (183 теста на 22.09.2026). Устройство стенда и CI — `README.md`, разделы «Тесты» и «CI».
- Что чем закреплено: `test_auth.py` — initData, register, login, `/me`, rate limit; `test_reading.py` — автомат, владение, `/start`, история, сбои LLM; `test_infra.py` — загрузочные проверки, старт только на head, совпадение моделей со схемой, уникальность цикла; `test_astrology.py` — `/astrology/bonus`; `test_llm_client.py` — клиент провайдера из настроек (URL, ключ, `OpenAI-Project`, заголовок логирования, модель); `test_llm_prompts.py` — правила персоны в промптах толкования и синтеза, очистка ответа `clean_llm_output`; `test_safety.py` — фразы, которые `is_crisis_message` ловит и не ловит, `CRISIS_REPLY` вместо LLM в `/interpret` и `/synthesis`.
- Каждое изменение поведения закрывай тестом. Готовые шаги — в `tests/helpers.py` (`sign_init_data`, `auth_headers`, `register`, `start_reading`, `run_cycle`, `synthesize`, `parse_sse`, `db_rows`); фикстуры `client`, `llm` (`llm.fail = True` — сбой провайдера, `llm.calls` — сделанные вызовы), `rate_limits_on`. ruff проверяет только корректность (`E9`, `F`).

### 4. Изменить схему БД

Общий порядок — `README.md`, раздел «Миграции». Здесь то, чего там нет.

1. Все три модели — в `backend/models/user.py`. Индексы и ограничения — в `__table_args__` с явными именами (`uq_...`, `ix_...`); рядом с каждым Python `default` держи такой же `server_default`, как во всех нынешних моделях: `alembic/env.py` сравнивает и server default, так что `alembic check` ловит расхождение модели с базой.
2. Генерируй и проверяй на временной базе, не на `morlana_db`:

```powershell
docker compose exec -T db psql -U user -d postgres -c "CREATE DATABASE morlana_scratch"
$db = "DATABASE_URL=postgresql+psycopg://user:pass@db:5432/morlana_scratch"
docker compose run --rm --no-deps -e $db -v ./backend:/app backend alembic upgrade head
docker compose run --rm --no-deps -e $db -v ./backend:/app backend alembic revision --autogenerate -m "add something"
docker compose run --rm --no-deps -e $db -v ./backend:/app backend alembic upgrade head
docker compose run --rm --no-deps -e $db -v ./backend:/app backend alembic check   # "No new upgrade operations detected."; до upgrade: "Target database is not up to date."
docker compose exec -T db psql -U user -d postgres -c "DROP DATABASE morlana_scratch"   # после работы
```

3. Сгенерированный файл (`alembic/versions/YYYYMMDD_slug.py`, дата по UTC) вычитай руками и допиши `downgrade()`. Попав в образ (`docker compose build`, `up --build`, `start.ps1`), он применится к `morlana_db` при ближайшем запуске `migrate` (инвариант 9). URL базы Alembic берёт только из `DATABASE_URL`; `sqlalchemy.url` в `alembic.ini` пуст намеренно.
4. Миграция должна пережить реальную базу, а не только пустую: в базе владельца были объекты, созданные мимо миграций, поэтому `d2e3f4a5b6c7` написана идемпотентной. Необратимые шаги (DROP) — только с явного согласия владельца.
5. К `morlana_db` миграцию применяют с разрешения и после бэкапа. Дамп снимай внутри контейнера и копируй наружу файлом: перенаправление `>` в PowerShell 5.1 портит дамп. Из Git Bash — с `MSYS_NO_PATHCONV=1` перед каждой командой (задача 2).

```powershell
$name = "morlana_db_$(Get-Date -Format yyyyMMdd_HHmm).dump"
docker compose exec -T db pg_dump -U user -Fc -f /tmp/$name morlana_db
docker compose exec -T db pg_restore -l /tmp/$name | Select-String "TABLE DATA"   # нужны users, tarot_sessions, reading_cycles, alembic_version
docker compose cp db:/tmp/$name C:\Users\user\morlana-backups\$name
docker compose exec -T db rm -f /tmp/$name
```

### 5. Добавить или изменить эндпоинт

- Слои: `routes/` (HTTP, авторизация, оркестрация) -> `services/` (домен, Redis, LLM) -> `models/` и `schemas/`. Импорты абсолютные от корня backend (`from config import settings`). Сервисы бросают типизированные ошибки (`ReadingNotFound`, `InvalidTransition`), роуты переводят их в HTTP.
- Сигнатура как у соседей: `request: Request, req: <Schema>, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)`. Первая строка — `user = await _get_user_from_init_data(initData, db)`; всё, что принимает `session_id`, следом вызывает `_get_owned_session`. Хелперы живут в `routes/reading.py`.
- Схемы — в `schemas/tarot.py` с экспортом через `schemas/__init__.py` (у `routes/auth.py` они в самом файле). Новый роутер подключай в `routes/__init__.py` и `main.py`.
- Коды: 401 авторизация, 404 нет или чужое, 409 конфликт и неверное состояние, 400 не выполнено предусловие, 422 валидация, 429 лимит, 502 сбой LLM в `/synthesis`. `detail` — короткая английская строка.
- Rate limit стоит только на `/api/v1/auth/*` (slowapi, ключ — реальный IP из `X-Forwarded-For`); `request: Request` в сигнатуре нужен slowapi.

### 6. Изменить флоу расклада

- Эндпоинты расклада (`/start`, `/ask`, `/draw`, `/interpret`, `/next`, `/synthesis`, `/state`, `/active`, `/history`) живут под `/api/v1/tarot/reading`. Автомат: `ReadingState`, `VALID_TRANSITIONS`, `MAX_CYCLES = 6` в `services/reading.py` (`/state` при этом отдаёт `max_cycles=6` литералом). Продуктовые правила и известные пробелы флоу — `instructions.md`, разделы 5 и 7.
- Переходы в роутах делай только через `_apply_transition`: неверное состояние -> 409, никогда 500 (`/interpret` без вопроса или без карты отвечает 400 ещё до перехода). `/ask`, `/draw`, `/interpret` и `/next` после проверки владельца зовут `_refresh_session_ttl`, чтобы ключи расклада не истекли под живым `:state`; `/start` и `/synthesis` его не вызывают.
- Хранение: Redis держит незавершённое (`reading:{sid}:state|cycle|question|card|cycle_data`, TTL 3600 с; строки пишутся как есть, остальное JSON, а при чтении всё идёт через `json.loads`, так что вопрос вида `42` вернётся числом), Postgres — долговечное (`tarot_sessions`, `reading_cycles`). Через час без действий расклад недоступен UI, следующий `/start` его заархивирует или удалит. `RedisService` глотает ошибки: отказ Redis выглядит как 404 `Reading not found`, сбой подключения при старте — только warning.
- `/synthesis` не живой стрим: ответ LLM собирается целиком, коммитится (`status='archived'`), затем проигрывается чанками. Сбой или пустой ответ LLM -> 502 `Synthesis failed`, расклад не архивируется, остаётся в `ЗАВЕРШЕНО`, повтор допустим. Клиент ключ `error` в SSE игнорирует: о сбое `/interpret` экран узнаёт, перечитав `/state`.
- FastAPI 0.115 закрывает `Depends(get_db)` ДО выполнения тела `StreamingResponse`. Генератор `/interpret` всё ещё пишет в `db`; это работает лишь за счёт переоткрытия `AsyncSession` и `expire_on_commit=False`. Не добавляй в SSE-генераторы логики, завязанной на сессию запроса, и не обновляй FastAPI мимоходом; исправление — этап 3.
- Ошибка провайдера LLM (у MiMo пустой баланс — 402; у Yandex AI Studio 402 не бывает, ждите 401/403 при проблеме с ключом, ролью или платёжным аккаунтом и 429 при исчерпании квот): `/interpret` завершится SSE-сообщением с ключом `error`, расклад останется в `ИНТЕРПРЕТАЦИЯ`; `/synthesis` ответит 502. Это не баг кода.
- Модерация Yandex включена по умолчанию: вместо толкования может прийти заглушка вида «Я не могу обсуждать эту тему...», возможно с `finish_reason` `content_filter`. Код `finish_reason` не смотрит: такой текст сохранится как обычное толкование или синтез, и только пустой ответ считается сбоем.

### 7. Добавить расклад или колоду

- Сейчас есть один расклад `prompts/spreads/one-card.json` и одна колода `frontend/public/decks/rider-waite/`. `SPREADS` в `services/llm.py` — словарь, заполненный вручную; из JSON в промпт идут `system_prompt`, `position_rules` и `aggregation_rules.additional_constraints`, параметром вызова LLM — только `max_tokens` (`temperature` и `card_count` игнорируются); `layout_type` в `/start` принимается и игнорируется; `SYNTHESIS_PROMPT` — константа в Python. Перевёрнутых карт и `deck_id` нет.
- Хранилище и API везде однокарточные: `reading_cycles.card_id` — один INT, Redis `reading:{sid}:card` — один int, `/draw` зовёт `draw_cards(1)[0]`, `ReadingDrawResponse` = `{card_id, card_name, state}`, `ReadingStateResponse.current_card` — int. Списки уже принимают только `cycle_data[].cards` и построители промпта.
- Поэтому расклад на несколько карт — это миграция, смена контракта API и правки `ReadingScreen` и `cardMap`, а не новый JSON. Реестр раскладов из `prompts/spreads/*.json`, контракт `DrawnCard {deck_id, card_id, position, reversed, name, image}` и хук `useReadingSession` — содержание этапа 2: не строй параллельную абстракцию, согласуй объём с владельцем.
- `backend/.dockerignore` исключает `*.md` только в корне контекста, поэтому `prompts/persona.md` попадает в образ. Замена на `**/*.md` уронит импорт `services/llm.py`.

### 8. Править UI

- Экраны — строка `screen` в `App.tsx` (`login | onboarding | dashboard | reading | history`), состояние лежит в `localStorage['morlana_state']`, `?reset=1` его сбрасывает. Весь HTTP идёт через `src/api/client.ts` и всегда с `initData`; ошибки — `ApiError{status, detail}`, каждый экран сам переводит статусы в русские сообщения. Типы ответов объявляются локально в компоненте.
- На первом рендере `initData` пуст: эффекты обязаны перезапускаться, когда он появится. Держи принятые приёмы: флаг `cancelled` в эффектах, `isMountedRef`, счётчик `attempt` для кнопок повтора, `aria-busy` на ждущей кнопке.
- Стили — обычный CSS в `src/styles/`: `global.css` плюс по файлу на экран (`LoginScreen` делит `onboarding.css` с `Onboarding`), kebab-case, без CSS-переменных (палитра повторяется литералами), анимации только на CSS keyframes, без Framer Motion.
- Шрифты Almendra и Babylonica не содержат кириллицы: русский текст рисуется запасным шрифтом. Учитывай это, оценивая макеты.
- `npm run dev` настроен на порт 3000 (`vite.config.ts`), который уже публикует контейнер frontend, и не проксирует API (нужен `VITE_API_URL=http://localhost:8000`), а при `DEV_MODE=false` API в браузере всё равно ответит 401. Реальная проверка UI — внутри Telegram через ngrok, с разрешения.

### 9. Проверить API руками

- Каждый запрос несёт `Authorization: Bearer <initData>`. Исключение — `POST /api/v1/astrology/bonus`: он подключён и работает, но берёт `initData` из тела; фронтенд его не вызывает. OpenAPI открыт на `http://localhost:8000/docs`; nginx (а значит и ngrok) проксирует только `/api/` и `/health`.
- В Git Bash `curl -d` с кириллицей портит тело запроса: клади JSON в файл UTF-8 и отправляй `--data-binary @file.json`. Вызовы `/interpret` и `/synthesis` на живом стеке стоят денег (инвариант 13).

### 10. Отгрузить изменение

- Перед коммитом: задача 3 целиком. `alembic check` отдельно запускать не нужно: его выполняет `test_infra.py` на `morlana_test`, а CI — ещё и на пустой базе. CI (`.github/workflows/ci.yml`) идёт на каждый push и pull request: ruff, миграции, `alembic check`, pytest, `tsc` и сборка фронтенда. После push проверь, что прогон зелёный: `gh run list --limit 1`.
- Коммиты — английские Conventional Commits в нижнем регистре со scope по желанию (`feat:`, `fix(auth):`, `chore(security):`); у крупных — тело списком по областям. Работа идёт в ветках `feature/*`, основная — `main`; `git push` только после разрешения.
- Предупреждения git `LF will be replaced by CRLF` — шум. BOM в начале `start.ps1` оставлен намеренно.

### 11. Сменить провайдера LLM

- Провайдер задают только переменные `LLM_*` в `.env` (правка `.env` и перезапуск стека — с разрешения владельца); код один для всех, клиент строит `build_client()` в `services/llm.py`. Блок-пример для Yandex закомментирован в `.env.example`. Пустое `LLM_DATA_LOGGING=` backend не примет: только `true` или `false`.
- Yandex AI Studio: `LLM_BASE_URL=https://ai.api.cloud.yandex.net/v1`; `LLM_PROJECT` — id каталога, уходит заголовком `OpenAI-Project`; `LLM_DATA_LOGGING=false` шлёт `x-data-logging-enabled: false` (Yandex не логирует запросы); модели — полные URI `gpt://<folder>/aliceai-llm-flash` и `gpt://<folder>/aliceai-llm`, а не короткие имена. При пустых `LLM_PROJECT` и `LLM_BASE_URL` SDK `openai` сам возьмёт `OPENAI_PROJECT_ID` и `OPENAI_BASE_URL` из окружения, если они там есть.
- MiMo: `mimo-v2-flash` (умолчание в `config.py`) снят 30.06.2026; `mimo-v2.5` и `mimo-v2.5-pro` (стоят в `.env.example`) перестают работать 21.10.2026, преемники — `mimo-v2.6-flash` и `mimo-v2.6-pro`.

## Карта кода

```
backend/main.py            app, lifespan (DEV_MODE guard, проверка ревизии, Redis), CORS, /health
backend/config.py          Settings (pydantic-settings); database.py — engine, get_db, check_schema_revision
backend/rate_limiter.py    slowapi limiter + client_ip;  logging_config.py — формат логов, приглушение httpx
backend/routes/            reading.py (+ общие auth-хелперы), auth.py, astrology.py; payments.py не подключён
backend/services/          auth, password, reading (автомат), redis, llm (клиент провайдера, промпты, имена карт), safety (кризисные сообщения), tarot (RNG), zodiac
backend/models/user.py     User, TarotSession, ReadingCycle;  backend/schemas/tarot.py — Pydantic-схемы
backend/prompts/           persona.md, spreads/one-card.json;  backend/alembic/versions/ — линейная цепочка, один head
backend/tests/             conftest.py (стенд), helpers.py, test_*.py;  .github/workflows/ci.yml — CI
frontend/src/              App.tsx, api/client.ts, hooks/useTelegram.ts, utils/cardMap.ts, components/, styles/
frontend/nginx.conf        прокси /api на backend, SSE без буферизации, X-Forwarded-For для rate limiter
docs/compose/, .mimocode/plans/   исторические планы, не источник истины
```

Мёртвый код, на который нельзя опираться: `SKIP_ONBOARDING`, `VITE_SKIP_ONBOARDING`, `Paywall.tsx` + `paywall.css`, `routes/payments.py` (не монтируй как есть: его модель запроса не совпадает с тем, что шлёт `Paywall.tsx`), `get_spread_config`, параметр `history` у `build_reading_prompt` и `stream_prediction`, `ReadingStartRequest.layout_type`, `services/zodiac.py` (достижим только через `/astrology/bonus`).
