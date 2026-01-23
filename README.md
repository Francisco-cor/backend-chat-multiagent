# Multi-Agent Chat Backend

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

A robust, enterprise-grade backend built with FastAPI, designed for the orchestration of advanced AI agents. This platform provides a scalable foundation for multi-agent applications, featuring native integration with Google GenAI (Gemini ecosystem) and OpenAI (GPT models).

---

## Technical Features

-   **Multi-Provider Architecture**: Comprehensive support for Google GenAI SDK and OpenAI.
-   **Advanced Language Models**: Configured for Gemini 3.0 Pro/Flash and High-Reasoning GPT models.
-   **Multimodal Integration**: Support for image and file processing across all supported providers.
-   **Google Search Grounding**: Integrated dynamic search capabilities utilizing advanced grounding tools.
-   **Security Infrastructure**: JWT-based authentication implementing OAuth2 and passlib (bcrypt).
-   **Request Management**: Advanced rate limiting via slowapi to ensure service stability and prevent abuse.
-   **Data Persistence**: Asynchronous PostgreSQL integration with SQLAlchemy for efficient conversation history management.
-   **Deployment Ready**: Fully containerized environment using Docker and Docker Compose.

---

## Technology Stack

-   **Framework**: [FastAPI](https://fastapi.tiangolo.com/)
-   **AI SDKs**: `google-genai` (2025 Standard), `openai`
-   **Database**: [PostgreSQL](https://www.postgresql.org/) with [SQLAlchemy](https://www.sqlalchemy.org/) (Async)
-   **Migrations**: [Alembic](https://alembic.sqlalchemy.org/)
-   **Security**: [Python-jose](https://python-jose.readthedocs.io/), [Passlib](https://passlib.readthedocs.io/)
-   **Validation**: [Pydantic v2](https://docs.pydantic.dev/)

---

## Project Structure

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

## Installation and Setup

### Prerequisites

-   Python 3.10+
-   PostgreSQL
-   Docker and Docker Compose (Optional)
-   API Credentials for Google Cloud or OpenAI

### 1. Repository Setup

```bash
git clone https://github.com/Francisco-cor/backend-chat-multiagent.git
cd backend-chat-multiagent
```

### 2. Environment Configuration

Initialize the environment variables using the provided template:

```bash
cp .env.example .env
```

**Required Configurations**:
- `GOOGLE_API_KEY`: Google AI Studio or Cloud API key.
- `OPENAI_API_KEY`: OpenAI API key.
- `DATABASE_URL`: Connection string (e.g., `postgresql+asyncpg://user:pass@localhost/dbname`).
- `SECRET_KEY`: Cryptographically secure string for JWT signing.

### 3. Local Deployment

```bash
# Initialize virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install requirements
pip install -r requirements.txt

# Start the application server
uvicorn app.main:app --reload
```

### 4. Containerized Deployment

```bash
docker-compose up --build
```

---

## API Documentation

Interactive documentation is available at the following endpoints:
-   **Swagger UI**: `http://localhost:8000/docs`
-   **ReDoc**: `http://localhost:8000/redoc`

### API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/auth/register` | User identity registration |
| `POST` | `/api/v1/auth/token` | JWT access token acquisition |
| `POST` | `/api/v1/chat/` | Multi-agent communication interface |
| `GET` | `/` | System health check and model availability |

---

## Security and Reliability

-   **Rate Limiting**: Configured per endpoint to ensure high availability and prevent resource exhaustion.
-   **Context Management**: Automated session handling for consistent multi-turn agent interactions.
-   **Search Grounding**: Available for Gemini-based models via the `use_search` parameter.

---

## License

This project is licensed under the MIT License. Refer to the [LICENSE](LICENSE) file for comprehensive details.

---
*Developed for the Clara Virtual Secretary project.*
