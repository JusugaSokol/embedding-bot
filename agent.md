Embedding Bot Architecture Notes
================================

Project Purpose
---------------
The Telegram bot accepts DOCX, CSV, TXT and Markdown files, extracts their text, and stores both the original files and derived embeddings in PostgreSQL. The text is segmented and routed through a LangGraph workflow that now uses the OpenAI GPT embedding API (`text-embedding-3-small`) to produce 1536‑dimensional vectors suitable for semantic search and retrieval.

Technology Stack
----------------
1. Telegram bot: `python-telegram-bot[asyncio]` (async handlers and polling/webhook helpers).
2. Backend: Django 5 with `django-environ` for configuration management.
3. Orchestration: LangGraph for building the embedding agent workflow.
4. Embeddings: Official `openai` Python SDK.
5. Storage: PostgreSQL + `pgvector` (1536 dimensions) for the n8n-embed table.
6. Parsing: `python-docx` for DOCX, standard libs for CSV/TXT/MD.
7. Segmentation: `nltk` sentence tokeniser (`punkt` models).
8. Testing: `pytest`, `pytest-django`, `pytest-asyncio`.

Environment Setup
-----------------
1. Create a virtual environment and install dependencies:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Populate `.env` with:
   ```
   DJANGO_SECRET_KEY=...
   DEBUG=True
   ALLOWED_HOSTS=127.0.0.1,localhost

   PRIMARY_DB_NAME=supabase_primary_db
   PRIMARY_DB_USER=supabase_primary_user
   PRIMARY_DB_PASSWORD=...
   PRIMARY_DB_HOST=your-supabase-host.supabase.co
   PRIMARY_DB_PORT=5432

   VECTOR_DB_NAME=...
   VECTOR_DB_USER=...
   VECTOR_DB_PASSWORD=...
   VECTOR_DB_HOST=your-vector-host.supabase.co
   VECTOR_DB_PORT=5432

   TELEGRAM_TOKEN=...
   OPENAI_API_KEY=
   ```
   Leave `OPENAI_API_KEY` empty in version-controlled examples; fill it locally.
3. Apply migrations: `python manage.py migrate`.
4. Download NLTK data if missing: the code automatically calls `nltk.download("punkt")`/`punkt_tab`.

LangGraph Embedding Agent
-------------------------
* The agent (`embeddings/agent.py`) initialises the OpenAI client with `OPENAI_API_KEY`. Any missing key raises a clear exception during instantiation.
* Default model: `text-embedding-3-small` (1536‑dim vectors). Adjust via the constructor if needed.
* Each node call:
  ```python
  from openai import OpenAI
  import os

  client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

  response = client.embeddings.create(
      model="text-embedding-3-small",
      input=segment_text,
  )
  embedding_vector = response.data[0].embedding
  ```
* The graph batches work (`SEGMENT_BATCH_SIZE`), retries transient errors (`RateLimitError`, `APIConnectionError`, `APITimeoutError`, 429 responses) with incremental backoff, and sleeps between requests to ease rate limits.

Vector Storage
--------------
* Model: `ingestion.models.N8NEmbed` with `VectorField(dimensions=1536)`.
* Migration `0003_recreate_n8n_embed` drops the old pgvector table (no backup) and recreates it with the correct dimension. Apply it to Supabase before running the updated code.
* Supabase manual SQL (run once, destructive):
  ```sql
  drop table if exists "n8n-embed" cascade;
  create table "n8n-embed" (
      id bigserial primary key,
      tittle varchar(255) not null,
      body text not null,
      embeding vector(1536) not null
  );
  ```

Ingestion Flow
--------------
1. Validation – block unsupported extensions and files over 15 MB.
2. Storage – keep the original upload in Django storage.
3. Parsing – convert documents to raw text.
4. Segmentation – use `segment_text` to create sentence clusters.
5. Embedding – call `EmbeddingAgent.embed_texts` (LangGraph pipeline).
6. Persistence – delete any previous entries for the file, then bulk insert new vectors.
7. Export – `build_export_archive` assembles a zip with the original file and `segments.json`.

Testing Checklist
-----------------
* Upload/store: confirm status transitions and validation errors.
* Segmentation: ensure `segment_text` returns non-empty, informative chunks.
* Embedding services: stub `EmbeddingAgent` to return deterministic 1536-length vectors and verify database writes.
* Export: confirm archive contents and JSON payload integrity.
* End-to-end: run Django + Telegram handlers in test settings with mocked APIs.

Operational Notes
-----------------
* Guard Telegram responses with informative error messages when OpenAI is unavailable.
* Monitor OpenAI usage and latency; adjust `request_delay` or batching if rate limits trigger often.
* Keep `.env`, `venv/`, temporary exports, and migrations-specific artefacts out of version control (see `.gitignore`).
* Rotate API keys periodically and prefer secrets managers for production deployments.
