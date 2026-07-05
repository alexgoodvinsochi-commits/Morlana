# User History Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сохранять последние 3 расклада пользователя и показывать их в Telegram Mini App.

**Architecture:** Добавить поля в существующие таблицы (tarot_sessions, reading_cycles), сохранять synthesis и card_name, создать endpoint для истории, добавить frontend компонент.

**Tech Stack:** SQLAlchemy, Alembic, FastAPI, React, TypeScript

## Global Constraints

- Авторизация через Telegram initData (уже работает)
- Telegram-only (без паролей)
- История: последние 3 расклада
- Приватность: тексты интерпретаций не доступны извне

---

### Task 1: Database Migration

**Covers:** [S3]

**Files:**
- Create: `backend/alembic/versions/20260705_add_history_fields.py`
- Modify: `backend/models/user.py`

**Interfaces:**
- Consumes: существующие модели TarotSession, ReadingCycle
- Produces: новые поля в таблицах

- [ ] **Step 1: Создать миграцию**

```python
# backend/alembic/versions/20260705_add_history_fields.py
"""Add history fields

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c8d9e0f1a2'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('tarot_sessions', sa.Column('synthesis', sa.Text(), nullable=True))
    op.add_column('tarot_sessions', sa.Column('spread_name', sa.String(100), server_default='one-card'))
    op.add_column('tarot_sessions', sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()))
    op.add_column('reading_cycles', sa.Column('card_name', sa.String(100), nullable=True))

def downgrade() -> None:
    op.drop_column('reading_cycles', 'card_name')
    op.drop_column('tarot_sessions', 'updated_at')
    op.drop_column('tarot_sessions', 'spread_name')
    op.drop_column('tarot_sessions', 'synthesis')
```

- [ ] **Step 2: Обновить ORM модели**

```python
# backend/models/user.py - TarotSession
class TarotSession(Base):
    # ... существующие поля ...
    synthesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    spread_name: Mapped[str] = mapped_column(String(100), default="one-card")
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

# backend/models/user.py - ReadingCycle
class ReadingCycle(Base):
    # ... существующие поля ...
    card_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
```

- [ ] **Step 3: Применить миграцию**

```bash
docker compose exec backend alembic upgrade head
```

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/ backend/models/user.py
git commit -m "feat: add history fields to tarot_sessions and reading_cycles"
```

---

### Task 2: Backend - Save card_name and synthesis

**Covers:** [S4]

**Files:**
- Modify: `backend/routes/reading.py`

**Interfaces:**
- Consumes: ReadingCycle model, TarotSession model
- Produces: данные сохраняются в PostgreSQL

- [ ] **Step 1: Добавить card_name в reading_interpret**

```python
# backend/routes/reading.py - в reading_interpret, после line 207
reading_cycle = ReadingCycle(
    session_id=req.session_id,
    cycle_number=cycle_count,
    question=question,
    card_id=cards[0],
    card_name=get_card_name(cards[0]),  # ДОБАВИТЬ
    interpretation=cleaned_answer,
)
```

- [ ] **Step 2: Добавить synthesis в reading_synthesis**

```python
# backend/routes/reading.py - в reading_synthesis, после сохранения статуса
if tarot_session:
    tarot_session.status = "archived"
    tarot_session.synthesis = cleaned_answer  # ДОБАВИТЬ
    await db.commit()
```

- [ ] **Step 3: Проверить работоспособность**

Запустить расклад и проверить:
```bash
docker compose exec db psql -U user -d morlana_db -c "SELECT card_name FROM reading_cycles ORDER BY id DESC LIMIT 3;"
docker compose exec db psql -U user -d morlana_db -c "SELECT synthesis IS NOT NULL as has_synthesis FROM tarot_sessions ORDER BY created_at DESC LIMIT 3;"
```

- [ ] **Step 4: Commit**

```bash
git add backend/routes/reading.py
git commit -m "feat: save card_name and synthesis to PostgreSQL"
```

---

### Task 3: Backend - History Endpoint

**Covers:** [S4]

**Files:**
- Modify: `backend/routes/reading.py`
- Modify: `backend/schemas/tarot.py`

**Interfaces:**
- Consumes: Telegram initData, User model, TarotSession, ReadingCycle
- Produces: ReadingHistoryResponse

- [ ] **Step 1: Добавить схему ответа**

```python
# backend/schemas/tarot.py - добавить
class CycleHistory(BaseModel):
    cycle_number: int
    question: str
    card_id: int
    card_name: str | None

class ReadingHistoryItem(BaseModel):
    session_id: str
    spread_name: str
    created_at: datetime
    cycle_count: int
    synthesis: str | None
    cycles: list[CycleHistory]

class ReadingHistoryResponse(BaseModel):
    readings: list[ReadingHistoryItem]
```

- [ ] **Step 2: Добавить endpoint**

```python
# backend/routes/reading.py - добавить
@router.get("/history", response_model=ReadingHistoryResponse)
async def reading_history(request: Request, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)):
    user = await _get_user_from_init_data(initData, db)

    # Получить последние 3 завершённые сессии
    sessions_result = await db.execute(
        select(TarotSession)
        .where(TarotSession.user_id == user.telegram_id)
        .where(TarotSession.status == "archived")
        .order_by(TarotSession.created_at.desc())
        .limit(3)
    )
    sessions = sessions_result.scalars().all()

    readings = []
    for session in sessions:
        cycles_result = await db.execute(
            select(ReadingCycle)
            .where(ReadingCycle.session_id == session.id)
            .order_by(ReadingCycle.cycle_number)
        )
        cycles = cycles_result.scalars().all()

        readings.append(ReadingHistoryItem(
            session_id=session.id,
            spread_name=session.spread_name or "one-card",
            created_at=session.created_at,
            cycle_count=session.cycle_count,
            synthesis=session.synthesis,
            cycles=[CycleHistory(
                cycle_number=c.cycle_number,
                question=c.question,
                card_id=c.card_id,
                card_name=c.card_name,
            ) for c in cycles],
        ))

    return ReadingHistoryResponse(readings=readings)
```

- [ ] **Step 3: Проверить endpoint**

```bash
curl -H "Authorization: Bearer dev" http://localhost:8000/api/v1/tarot/reading/history
```

- [ ] **Step 4: Commit**

```bash
git add backend/routes/reading.py backend/schemas/tarot.py
git commit -m "feat: add reading history endpoint"
```

---

### Task 4: Frontend - ReadingHistory Component

**Covers:** [S5]

**Files:**
- Create: `frontend/src/components/ReadingHistory.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles/app.css`

**Interfaces:**
- Consumes: GET /api/v1/tarot/reading/history
- Produces: экранный компонент

- [ ] **Step 1: Создать компонент**

```tsx
// frontend/src/components/ReadingHistory.tsx
import { useState, useEffect } from 'react';
import { apiGet } from '../api/client';
import { getCardImage, getCardName } from '../utils/cardMap';

interface CycleHistory {
  cycle_number: number;
  question: string;
  card_id: number;
  card_name: string | null;
}

interface ReadingHistoryItem {
  session_id: string;
  spread_name: string;
  created_at: string;
  cycle_count: number;
  synthesis: string | null;
  cycles: CycleHistory[];
}

interface Props {
  initData: string;
  onBack: () => void;
}

export default function ReadingHistory({ initData, onBack }: Props) {
  const [readings, setReadings] = useState<ReadingHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    const loadHistory = async () => {
      try {
        const data = await apiGet<{ readings: ReadingHistoryItem[] }>(
          '/api/v1/tarot/reading/history',
          initData,
        );
        setReadings(data.readings);
      } catch {
        setError('Не удалось загрузить историю.');
      } finally {
        setLoading(false);
      }
    };
    loadHistory();
  }, [initData]);

  if (loading) return <div className="reading-loading"><span className="spinner" /> Загрузка...</div>;
  if (error) return <div className="error-msg"><p>{error}</p><button onClick={onBack}>Назад</button></div>;

  return (
    <div className="reading-history-screen">
      <h2>Мои расклады</h2>
      <button onClick={onBack} className="exit-btn">Назад</button>

      {readings.length === 0 ? (
        <p className="empty-history">У вас пока нет раскладов</p>
      ) : (
        readings.map((reading) => (
          <div key={reading.session_id} className="history-item">
            <div
              className="history-item-header"
              onClick={() => setExpanded(expanded === reading.session_id ? null : reading.session_id)}
            >
              <span className="history-date">
                {new Date(reading.created_at).toLocaleDateString('ru-RU')}
              </span>
              <span className="history-cycles">{reading.cycle_count} циклов</span>
              <span className="history-expand">{expanded === reading.session_id ? '▲' : '▼'}</span>
            </div>

            {expanded === reading.session_id && (
              <div className="history-item-details">
                {reading.cycles.map((cycle) => (
                  <div key={cycle.cycle_number} className="history-cycle">
                    <div className="history-cycle-header">
                      <span className="cycle-number">Цикл {cycle.cycle_number}</span>
                      <img
                        src={getCardImage(cycle.card_id)}
                        alt={getCardName(cycle.card_id)}
                        className="history-card-thumb"
                      />
                    </div>
                    <p className="history-question">{cycle.question}</p>
                    <p className="history-card-name">{cycle.card_name || getCardName(cycle.card_id)}</p>
                  </div>
                ))}

                {reading.synthesis && (
                  <div className="history-synthesis">
                    <h4>Синтез</h4>
                    <p>{reading.synthesis}</p>
                  </div>
                )}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
```

- [ ] **Step 2: Обновить App.tsx**

```tsx
// frontend/src/App.tsx - добавить импорт и экран
import ReadingHistory from './components/ReadingHistory';

type Screen = 'onboarding' | 'reading' | 'history';

// Внутри App():
const [showHistory, setShowHistory] = useState(false);

// В return:
{state.screen === 'reading' && !showHistory && (
  <ReadingScreen initData={initData} onExit={handleExitReading} onHistory={() => setShowHistory(true)} />
)}

{showHistory && (
  <ReadingHistory initData={initData} onBack={() => setShowHistory(false)} />
)}
```

- [ ] **Step 3: Добавить стили**

```css
/* frontend/src/styles/app.css - добавить */
.reading-history-screen {
  padding: 20px;
}

.history-item {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(196, 162, 101, 0.15);
  border-radius: 12px;
  margin-bottom: 12px;
  overflow: hidden;
}

.history-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  cursor: pointer;
}

.history-date {
  color: #c4a265;
  font-weight: 600;
}

.history-cycles {
  color: #a89878;
  font-size: 14px;
}

.history-expand {
  color: #c4a265;
}

.history-item-details {
  padding: 0 16px 16px;
  border-top: 1px solid rgba(196, 162, 101, 0.1);
}

.history-synthesis {
  margin-top: 12px;
  padding: 12px;
  background: rgba(196, 162, 101, 0.08);
  border-radius: 8px;
}

.history-synthesis h4 {
  color: #c4a265;
  margin-bottom: 8px;
}

.empty-history {
  text-align: center;
  color: #a89878;
  padding: 40px;
}
```

- [ ] **Step 4: Проверить в браузере**

Открыть http://localhost:3000 → проверить кнопку "Мои расклады" → проверить историю

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ReadingHistory.tsx frontend/src/App.tsx frontend/src/styles/app.css
git commit -m "feat: add reading history UI component"
```

---

### Task 5: Integration Test

**Covers:** [S9]

**Files:**
- Нет (тестирование через API)

**Interfaces:**
- Consumes: все предыдущие задачи
- Produces: проверка работоспособности

- [ ] **Step 1: Полный тест через API**

```bash
# Начать расклад
$ sid = (Invoke-RestMethod -Uri "http://localhost:8000/api/v1/tarot/reading/start" -Method POST -Body '{"initData":"dev"}' -ContentType "application/json").session_id

# Пройти 6 циклов
for ($i=1; $i -le 6; $i++) {
    Invoke-RestMethod -Uri "http://localhost:8000/api/v1/tarot/reading/ask" -Method POST -Body (@{initData="dev"; session_id=$sid; question="Вопрос $i"} | ConvertTo-Json) -ContentType "application/json"
    Invoke-RestMethod -Uri "http://localhost:8000/api/v1/tarot/reading/draw" -Method POST -Body (@{initData="dev"; session_id=$sid} | ConvertTo-Json) -ContentType "application/json"
    Invoke-WebRequest -Uri "http://localhost:8000/api/v1/tarot/reading/interpret" -Method POST -Body (@{initData="dev"; session_id=$sid} | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 30
    if ($i -lt 6) { Invoke-RestMethod -Uri "http://localhost:8000/api/v1/tarot/reading/next" -Method POST -Body (@{initData="dev"; session_id=$sid} | ConvertTo-Json) -ContentType "application/json" }
}

# Синтез
Invoke-WebRequest -Uri "http://localhost:8000/api/v1/tarot/reading/synthesis" -Method POST -Body (@{initData="dev"; session_id=$sid} | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 30

# Проверить историю
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/tarot/reading/history" -Headers @{"Authorization"="Bearer dev"}
```

- [ ] **Step 2: Проверить в Telegram**

Открыть Mini App → пройти расклад → нажать "Мои расклады" → проверить историю

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: complete user history feature"
git push origin main
```
