# Embedding Bot

A Django-based Telegram bot that ingests user documents, extracts their text, and generates vector embeddings using the OpenAI GPT embedding API. The vectors are stored in PostgreSQL with pgvector for downstream semantic search or retrieval tasks.

## Features
- Async Telegram bot built on `python-telegram-bot` for uploads and status updates.
- Document ingestion pipeline with format-specific parsers (DOCX, CSV, TXT, Markdown).
- Text segmentation via NLTK before embedding.
- LangGraph-powered agent that handles batching and retries when calling the OpenAI embeddings endpoint.
- Storage of embeddings and metadata in PostgreSQL/pgvector, plus archive export for processed files.

## Requirements
- Python 3.12+
- PostgreSQL 14+ with the pgvector extension
- OpenAI API key

Key Python dependencies are listed in `requirements.txt` (Django, python-telegram-bot, langgraph, openai, nltk, etc.).

## Quick Start
1. **Clone & set up env**
   ```bash
   python -m venv venv
   venv\Scripts\activate  # or source venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Configure environment**
   Create `.env` at the project root (see template below) and fill in secrets plus database credentials.
3. **Apply migrations**
   ```bash
   python manage.py migrate
   ```
4. **Run services**
   ```bash
   python manage.py runserver  # Django admin/API
   python manage.py bot        # if you expose the Telegram bot via a custom command
   ```

## Environment Variables
Example `.env` contents:
```
DJANGO_SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

PRIMARY_DB_NAME=supabase_primary_db
PRIMARY_DB_USER=supabase_primary_user
PRIMARY_DB_PASSWORD=your-primary-password
PRIMARY_DB_HOST=your-supabase-host.supabase.co
PRIMARY_DB_PORT=5432

VECTOR_DB_NAME=supabase_vector_db
VECTOR_DB_USER=supabase_vector_user
VECTOR_DB_PASSWORD=your-vector-password
VECTOR_DB_HOST=your-vector-host.supabase.co
VECTOR_DB_PORT=5432

TELEGRAM_TOKEN=your-telegram-bot-token
OPENAI_API_KEY=your-openai-api-key
```

## Testing
Run the pytest suite (requires the test database to be configured):
```bash
pytest
```

## Project Layout
- `src/` – Django project code (bot, embeddings, ingestion, settings, tests).
- `venv/` – local virtual environment (ignored in version control).
- `.env` – private configuration values (ignored).
- `agent.md` – detailed internal documentation for the embedding pipeline.

## Additional Notes
- Ensure NLTK's `punkt` models are available; the code downloads them on demand.
- Embedding batches include retry logic, but you should monitor logs for rate limiting.
- Keep your `.env` and `venv` folders out of version control; see `.gitignore` for defaults.
- After pulling this version, apply migration `0003_recreate_n8n_embed` (or run the provided SQL) so the `n8n-embed` table is recreated with vector dimension 1536 to match OpenAI embeddings.
