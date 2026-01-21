# 🤖 Multi-Agent Chat Backend

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

A high-performance, production-ready backend built with **FastAPI**, designed to orchestrate cutting-edge AI models. This system serves as a robust foundation for multi-agent chat applications, featuring seamless integration with the latest **Google GenAI (Gemini 2.5/3.0)** and **OpenAI (GPT-5)** ecosystems.

---

## ✨ Key Features

-   **🌐 Multi-Provider Architecture**: Native support for Google GenAI SDK (v1.51+) and OpenAI.
-   **🧠 Next-Gen LLMs**: Pre-configured for Gemini 3.0 Pro/Flash and GPT-5 (Low/High effort reasoning).
-   **📷 Multimodal Capabilities**: Support for image and file processing across providers.
-   **🔍 Google Search Grounding**: Built-in dynamic search capabilities using Gemini's latest grounding tools.
-   **🔐 Enterprise Security**: JWT-based authentication with `OAuth2` and `passlib` (bcrypt).
-   **🚦 Advanced Rate Limiting**: Request throttling using `slowapi` to prevent abuse.
-   **🗄️ Persistent Context**: Asynchronous database integration (PostgreSQL via SQLAlchemy) for conversation history.
-   **🐳 Containerized**: Fully Dockerized setup with `docker-compose` for easy deployment.

---

## 🛠️ Tech Stack

-   **Framework**: [FastAPI](https://fastapi.tiangolo.com/)
-   **AI SDKs**: `google-genai` (2025 Standard), `openai` (v1.120+)
-   **Database**: [PostgreSQL](https://www.postgresql.org/) with [SQLAlchemy](https://www.sqlalchemy.org/) (Async)
-   **Migrations**: [Alembic](https://alembic.sqlalchemy.org/) (configurable)
-   **Security**: [Python-jose](https://python-jose.readthedocs.io/), [Passlib](https://passlib.readthedocs.io/)
-   **Validation**: [Pydantic v2](https://docs.pydantic.dev/)

---

## 📁 Project Structure

```text
.
├── app/
│   ├── api/ v1/          # API Endpoints (Chat, Auth)
│   ├── core/             # Configuration, Security, Rate Limiting
│   ├── db/               # Models, Sessions, Migrations
│   ├── schemas/          # Pydantic Schemas (Request/Response)
│   ├── services/         # Business Logic (LLM Providers, Chat Logic)
│   └── main.py           # Application Entry point
├── Dockerfile            # Container definition
├── docker-compose.yml    # Multi-container orchestration
├── requirements.txt      # Dependency list
└── .env.example          # Template for environment variables
```

---

## 🚀 Getting Started

### Prerequisites

-   Python 3.10+
-   PostgreSQL
-   Docker & Docker Compose (Optional)
-   API Keys for Google Cloud and/or OpenAI

### 1. Clone the Repository

```bash
git clone https://github.com/Francisco-cor/backend-chat-multiagent.git
cd backend-chat-multiagent
```

### 2. Environment Configuration

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

**Required Variables**:
- `GOOGLE_API_KEY`: Your Google AI Studio/Cloud key.
- `OPENAI_API_KEY`: Your OpenAI API key.
- `DATABASE_URL`: `postgresql+asyncpg://user:pass@localhost/dbname`
- `SECRET_KEY`: A secure random string for JWT signing.

### 3. Local Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload
```

### 4. Running with Docker

```bash
docker-compose up --build
```

---

## 📖 API Usage

The API provides interactive documentation at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

### Primary Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/auth/register` | User registration |
| `POST` | `/api/v1/auth/token` | Obtain JWT access token |
| `POST` | `/api/v1/chat/` | Send a message to the multi-agent system |
| `GET` | `/` | Health check & supported models |

---

## 🛡️ Security & Reliability

-   **Rate Limiting**: Configurable limits per endpoint to ensure service stability.
-   **State Management**: Conversation context is automatically managed and stored, allowing for deep multi-turn interactions.
-   **Grounding**: Google Search grounding is available for Gemini models by setting `use_search: true` in the chat request.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---
*Created with ❤️ by Clara Virtual Secretary project.*
