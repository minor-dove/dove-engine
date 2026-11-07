# Project DOVE — AI Desk Pet Backend

> **DOVE** is an AI-powered desk pet backend that provides mood-aware conversations, long-term conversational memory, deterministic proactive check-ins, daily routines, tasks, and reminders.

---

## 1. System Architecture

```
                  +---------------------------+
                  |  ESP32 Edge Device        |
                  |  - On-Device Camera Model |
                  |  - Wake-Word ("Dove")     |
                  +-------------+-------------+
                                |
                   MQTT Broker  |  (dove/devices/{id}/events, commands, status)
             [Eclipse Mosquitto :1883]
                                |
             +------------------+------------------+
             |                                     |
             v                                     v
+------------------------+             +------------------------+
|  DOVE Backend Worker   |             |  FastAPI Application   |
|  - MQTT Consumer       |             |  - REST APIs (/api/v1) |
|  - Deterministic Engine|             |  - Swagger UI (/docs)  |
|  - Persistent Scheduler|             |  - Health (/health)    |
+-----------+------------+             +-----------+------------+
            |                                      |
            +------------------+-------------------+
                               |
            +------------------v-------------------+
            | PostgreSQL + pgvector (dove_db)      |
            | - Mood Events & Streaks              |
            | - Multi-turn Conversation History    |
            | - Semantic Long-Term Memories (RAG)  |
            | - First-Class Tasks & Reminders      |
            | - Routines & Proactive Cooldowns     |
            +--------------------------------------+
```

---

## 2. Privacy Core Principles

- **Zero Camera Data on Backend**: The ESP32 edge device performs facial-expression classification locally.
- **Strict Privacy Guard**: The backend never accepts, transmits, or stores camera images, video frames, face embeddings, or raw sensor data.
- Any payload containing image or camera keys is immediately rejected with a `PrivacyViolationError`.
- Mood labels (Angry, Sad, Happy, Neutral, etc.) are treated strictly as **contextual hints**, never as clinical diagnoses or confirmed personal facts.

---

## 3. Mood Classification & Deterministic Trigger Rules

The edge device sends classification IDs every minute:

| ID | Emotion  | Proactive Trigger Eligible |
| -: | -------- | -------------------------- |
|  0 | Angry    | Yes (10 consecutive)      |
|  1 | Disgust  | No (Context only)         |
|  2 | Fear     | No (Context only)         |
|  3 | Happy    | No (Context only)         |
|  4 | Sad      | Yes (10 consecutive)      |
|  5 | Surprise | No (Context only)         |
|  6 | Neutral  | No (Context only)         |

### Trigger Behavior:
1. **10 Consecutive Sustained Events**: Only **Angry (0)** and **Sad (4)** can trigger an immediate proactive check-in after **10 consecutive valid inputs**.
2. **Independent Streak Tracking**: Angry and Sad streaks are tracked independently. Receiving any other mood resets both streaks. 5 Angry followed by 5 Sad does **not** qualify.
3. **Broken Continuity Detection**: If the time gap between consecutive events exceeds 150 seconds (> 2.5 minutes), the streak is broken and resets to 1.
4. **Duplicate & Stale Event Rejection**: Duplicate `event_id` records or stale/future timestamps are rejected and cannot falsely advance streaks.
5. **Repeated Check-in Prevention**: Once a qualifying streak initiates a conversation, the streak is marked as triggered. Subsequent events of the same mood do not trigger repeated conversations until a new qualifying streak is established.
6. **Active Session Context**: If a conversation is already active, incoming mood observations are attached as conversational context rather than opening duplicate sessions.
7. **30-Minute Proactive Cooldown**: An atomic 30-minute cooldown is enforced between proactive conversations. User-initiated conversations and reminders bypass this cooldown.

---

## 4. Technology Stack

- **Runtime**: Python 3.12+
- **API Framework**: FastAPI & Uvicorn
- **Database**: PostgreSQL 16 with `pgvector` & SQLAlchemy 2.0
- **Database Migrations**: Alembic
- **Hardware Messaging**: Eclipse Mosquitto & MQTT (`paho-mqtt`)
- **LLM Integration**: Groq API (`qwen/qwen3.8-27b` / `llama-3.1-8b-instant`)
- **Memory & RAG**: Semantic vector retrieval with provenance and false-trigger purge
- **Scheduler**: Persistent background scheduler for routines and reminders
- **Containerization**: Docker & Docker Compose
- **Testing**: `pytest`, `pytest-asyncio`, `pytest-mock`

---

## 5. Local Development & Setup

### Development Authentication Mode
For local development, **authentication and authorization requirements are disabled**:
- All FastAPI endpoints are accessible without tokens or headers.
- Mosquitto allows anonymous connections without credentials.
- Swagger UI (`http://localhost:8000/docs`) is immediately interactive.

### Running with Docker Compose

1. **Clone the repository and enter the directory**:
   ```bash
   cd DOVE-MINOR
   ```

2. **Configure environment variables**:
   ```bash
   cp .env.example .env
   ```
   Add your Groq API key in `.env`:
   ```ini
   GROQ_API_KEY=gsk_your_actual_key_here
   ```

3. **Start all services**:
   ```bash
   docker compose up -d --build
   ```

4. **Verify running containers**:
   - `dove_api`: FastAPI on port 8000
   - `dove_worker`: Background MQTT listener & scheduler
   - `dove_postgres`: PostgreSQL with pgvector on port 5432
   - `dove_mqtt`: Mosquitto broker on port 1883

5. **Access Swagger UI & Health Check**:
   - Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
   - Health Check: [http://localhost:8000/health](http://localhost:8000/health)

---

## 6. Running Locally Without Docker

1. **Create and activate a virtual environment**:
   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .\.venv\Scripts\Activate.ps1
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run database migrations / initialization**:
   ```bash
   python -c "from app.core.init_db import init_db; init_db()"
   ```

4. **Start the FastAPI application**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

5. **Start the background worker (in a separate terminal)**:
   ```bash
   python -m app.worker
   ```

6. **Run the automated test suite**:
   ```bash
   pytest -v
   ```

---

## 7. MQTT Hardware Topic Conventions

| Topic | Direction | Description |
| ----- | --------- | ----------- |
| `dove/devices/{device_id}/events` | ESP32 -> Backend | Mood classifications every minute (`mood_id`, `event_id`, `recorded_at`) |
| `dove/devices/{device_id}/conversation/message` | ESP32 -> Backend | User speech transcription after on-device wake-word detection |
| `dove/devices/{device_id}/status` | ESP32 -> Backend | Heartbeat, firmware version, and battery telemetry |
| `dove/devices/{device_id}/presence` | ESP32 -> Backend | `{"present": bool}` — user in front of the device; sessions only start while present |
| `dove/devices/{device_id}/privacy` | ESP32 -> Backend | `{"mode": "on"\|"off"}` retained — do-not-disturb; aborts running sessions |
| `dove/devices/{device_id}/commands` | Backend -> ESP32 | Speech prompts (`speak`), reminder alerts (`reminder_alert`), actions |

---

## 8. REST API Endpoints Overview

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| `GET` | `/health` | Application, database, and MQTT health check |
| `GET` | `/api/v1/conversations/sessions` | List conversation sessions |
| `GET` | `/api/v1/conversations/sessions/{id}` | Get session details and full multi-turn dialogue history |
| `POST` | `/api/v1/conversations/message` | Send user message and get AI response |
| `POST` | `/api/v1/conversations/sessions/{id}/false-trigger` | Flag false trigger & purge derived memories |
| `GET` | `/api/v1/tasks` | List tasks (filter by pending, completed, cancelled) |
| `POST` | `/api/v1/tasks` | Create a new task |
| `PATCH` | `/api/v1/tasks/{id}` | Update task title, description, due date, or status |
| `DELETE` | `/api/v1/tasks/{id}` | Delete a task |
| `GET` | `/api/v1/reminders` | List scheduled reminders |
| `POST` | `/api/v1/reminders` | Schedule a persistent reminder |
| `POST` | `/api/v1/reminders/{id}/acknowledge` | Acknowledge reminder receipt |
| `GET` | `/api/v1/preferences` | View quiet hours, routine times, timezone, and cooldown |
| `PUT` | `/api/v1/preferences` | Update companion preferences |
| `GET` | `/api/v1/routines/history` | View routine execution history |
| `POST` | `/api/v1/routines/trigger` | Manually test/trigger morning, midday, evening, or night routine |
| `GET` | `/api/v1/memories` | List active long-term memories |
| `POST` | `/api/v1/memories/search` | Semantically search long-term memories |
| `DELETE` | `/api/v1/memories/{id}` | Permanently delete a memory record |
| `POST` | `/api/v1/stress/sessions` | Start a stress session (planner does this automatically while the user is present) |
| `POST` | `/api/v1/stress/sessions/{id}/answer` | Submit an answer; returns next question or the final score |
| `GET` | `/api/v1/stress/days/{date}` | Day score = mean of completed session scores |
| `GET` | `/api/v1/stats` | Aggregated metrics (conversations, tasks, reminders, routines, mood history) |
