# Roadmap — Morlana

## Текущий статус

- Telegram Mini App: логин/пароль, онбординг, дашборд, расклады (1 карта, до 6 циклов), история (3 последних), синтез
- Backend: FastAPI + PostgreSQL + Redis + MiMo LLM
- Frontend: React 18 + TypeScript + Vite

---

## Ближайшие задачи

### 1. Админ-панель / Статистика

- [ ] **Счётчик сессий всего по базе** — общее количество раскладов (archived) в `tarot_sessions`
- [ ] **Счётчик сессий по каждому пользователю** — количество archived сессий на пользователя
- [ ] **Какие расклады делал пользователь** — список использованных `spread_name` + количество циклов + дата последнего расклада

**Реализация:**
- Новый эндпоинт `GET /api/v1/admin/stats` (или `GET /api/v1/user/stats` для自救)
- Агрегация: `COUNT(*)` по `tarot_sessions` с `GROUP BY user_id`
- Связь с `reading_cycles` для детализации по раскладам

### 2. Оплата

- [ ] Telegram Payments API (ЮKassa / Robokassa)
- [ ] Paywall экран (заглушка есть)
- [ ] Подписка: free tier (3 расклада) → платная подписка

### 3. Астрология

- [ ] Сбор даты/времени рождения (сейчас отложено)
- [ ] Вычисление знака зодиака на бэкенде
- [ ] Персонализация промптов LLM

### 4. Дизайн — Mystical Fluidity

- [ ] **T0: Reading Screen** — карта 3/4 экрана, свайп, overlay (`reading.css`, `ReadingScreen.tsx`)
- [ ] **T1: Кнопки** — hover/active + glow (`global.css`)
- [ ] **T2: Bottom Nav** — glassmorphism + blur (`bottomnav.css`)
- [ ] **T3: Индикатор загрузки** — pulse анимация (`reading.css`)
- [ ] **T4: Карта** — overlay с градиентом (`reading.css`)
- [ ] **T5: Переходы** — fadeSlideIn анимации (`reading.css`)
- [ ] **T6: Loading кнопки** — пульс (`global.css`)

Детали: `.mimocode/plans/1783595460537-calm-planet.md`

### 5. Прочее

- [ ] Очистка `SYNTHESIS_PROMPT` из llm.py → spreads JSON
- [ ] Synthesis button bug на 6-м цикле
- [ ] Тестовый пользователь "testuser" — удалить перед продом
- [ ] Rate limiting ( slowapi + nginx shared IP конфликт)

### 6. После MVP

- [ ] Рассылки (email / Telegram bot)
- [ ] Push-уведомления
- [ ] Haptic feedback (Telegram WebApp SDK)

---

## Архитектура фронтенда

### CSS: текущий статус

Разделён по компонентам (Вариант 2):

```
styles/
├── global.css          — сброс, body, кнопки, спиннер, ошибки
├── onboarding.css      — LoginScreen + Onboarding
├── dashboard.css       — UserDashboard
├── reading.css         — ReadingScreen
├── history.css         — ReadingHistory
├── bottomnav.css       — BottomNav
└── paywall.css         — Paywall
```

### CSS: миграция на CSS Modules / Tailwind (Вариант 3)

**Чекпоинт для миграции:**
- Количество компонентов > 15
- Или количество CSS файлов > 10
- Или появления конфликтов имён классов

**Признаки готовности:**
- Дублирование стилей между компонентами
- Сложность поиска нужного стиля
- Необходимость изоляции стилей (модалки, попапы)

**Реализация:**
- CSS Modules: каждый `.module.css` привязан к компоненту
- Tailwind: утилитарные классы, кастомизация через конфиг
- Или: CSS-in-JS (styled-components, emotion)
