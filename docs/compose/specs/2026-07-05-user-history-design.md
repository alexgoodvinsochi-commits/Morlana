# [S1] Problem

Пользователи не могут видеть историю своих раскладов. После закрытия приложения данные теряются (Redis TTL 1 час). Нет возможности вернуться к прошлым раскладам.

## [S2] Solution Overview

Сохранять последние 3 расклада в PostgreSQL и показывать их в Telegram Mini App. Авторизация — через Telegram `initData` (уже работает). Дополнительная регистрация не нужна.

## [S3] Database Changes

### tarot_sessions (добавить поля)

```sql
ALTER TABLE tarot_sessions ADD COLUMN IF NOT EXISTS synthesis TEXT;
ALTER TABLE tarot_sessions ADD COLUMN IF NOT EXISTS spread_name VARCHAR(100) DEFAULT 'one-card';
ALTER TABLE tarot_sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
```

### reading_cycles (добавить поле)

```sql
ALTER TABLE reading_cycles ADD COLUMN IF NOT EXISTS card_name VARCHAR(100);
```

## [S4] Backend Changes

### Новый эндпоинт: GET /api/v1/tarot/reading/history

Возвращает последние 3 завершённых сессии пользователя:

```json
{
  "readings": [
    {
      "session_id": "uuid",
      "spread_name": "one-card",
      "created_at": "2026-07-05T10:00:00Z",
      "cycle_count": 6,
      "synthesis": "текст синтеза...",
      "cycles": [
        {
          "cycle_number": 1,
          "question": "вопрос",
          "card_id": 20,
          "card_name": "Солнце"
        }
      ]
    }
  ]
}
```

### Изменения в существующих эндпоинтах

| Эндпоинт | Изменение |
|----------|-----------|
| `POST /reading/interpret` | Добавить `card_name=get_card_name(card_id)` в `ReadingCycle` |
| `POST /reading/synthesis` | Сохранять `synthesis` в `TarotSession.synthesis` |

### Модель TarotSession (обновить)

```python
class TarotSession(Base):
    # ... существующие поля ...
    synthesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    spread_name: Mapped[str] = mapped_column(String(100), default="one-card")
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=now)
```

### Модель ReadingCycle (обновить)

```python
class ReadingCycle(Base):
    # ... существующие поля ...
    card_name: Mapped[str | None] = mapped_column(String(100))
```

## [S5] Frontend Changes

### Новый компонент: ReadingHistory

Отображает последние 3 расклада:
- Дата и время
- Тип расклада
- Список карт и вопросов
- Текст синтеза (если есть)

### Изменения в App.tsx

Добавить экран `history` в роутинг:
- Кнопка "Мои расклады" на главном экране
- Экран истории с карточками раскладов

### Изменения в ReadingScreen.tsx

- После завершения расклада — кнопка "Мои расклады"
- При входе в расклад — опционально загрузить из истории

## [S6] Data Flow

1. Пользователь делает расклад (6 циклов + синтез)
2. Каждый цикл сохраняется в `reading_cycles` (с `card_name`)
3. Синтез сохраняется в `tarot_sessions.synthesis`
4. При запросе `/reading/history` — возвращаются последние 3 сессии с циклами

## [S7] Privacy

- История доступна только владельцу (проверка по `telegram_id`)
- Админка НЕ показывает тексты интерпретаций
- Данные хранятся в PostgreSQL (не в Redis)

## [S8] Migration

1. Создать миграцию Alembic для новых полей
2. Обновить модели ORM
3. Обновить reading routes (card_name, synthesis)
4. Добавить history endpoint
5. Добавить frontend компонент

## [S9] Verification

1. Сделать расклад → проверить что synthesis сохраняется
2. Проверить что card_name сохраняется в reading_cycles
3. Вызвать `/reading/history` → проверить 3 последних расклада
4. Проверить что история видна в Telegram Mini App
