Embedding Bot Architecture Notes
================================

Project Purpose
---------------
The Telegram bot now operates as a multi-tenant embedding service. Each Telegram user can onboard independently, provide their own Supabase and OpenAI credentials, and run document ingestion that stores both raw files and GPT-generated embeddings in Supabase. The application persists onboarding metadata and secrets in the local PostgreSQL instance so that returning users can resume work without re-entering credentials.

Technology Stack
----------------
1. Telegram bot: `python-telegram-bot[asyncio]` (async handlers, conversation states, onboarding wizard).
2. Backend: Django 5 + `django-environ` for base configuration; `django-fernet-fields` (or equivalent) for encrypting stored secrets.
3. Persistence: local PostgreSQL (default Django database) for bot metadata, user profiles, and encrypted credentials.
4. External storage: Supabase-hosted PostgreSQL with `pgvector` (1536 dimensions) for per-user embedding tables.
5. Embeddings: OpenAI SDK (`text-embedding-3-small` by default) with retry-aware LangGraph workflow.
6. Validation: `pydantic` models to normalise and validate all user-provided connection parameters.
7. Orchestration: LangGraph for the embedding pipeline; Celery remains optional for background ingestion if throughput grows.
8. Testing: `pytest`, `pytest-django`, `pytest-asyncio`, with factories for onboarding flows and credential mocks.

Environment Setup
-----------------
1. Create a virtual environment and install dependencies:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Populate `enbedingbot/.env` with project-wide defaults (used before the first user completes onboarding):
   ```
   DJANGO_SECRET_KEY=...
   DEBUG=True
   ALLOWED_HOSTS=127.0.0.1,localhost

   PRIMARY_DB_NAME=embedding_bot
   PRIMARY_DB_USER=embedding_bot
   PRIMARY_DB_PASSWORD=...
   PRIMARY_DB_HOST=127.0.0.1
   PRIMARY_DB_PORT=5432

   TELEGRAM_TOKEN=...
   OPENAI_API_KEY=
   FERNET_SECRET=base64-fernet-key
   ```
   The primary database hosts Django state, user metadata, and encrypted secrets. `OPENAI_API_KEY` may be left blank to force onboarding. `FERNET_SECRET` seeds secret-field encryption.
3. Apply migrations for Django core, `bot`, and `ingestion` apps: `python manage.py migrate`.
4. If the onboarding wizard should fall back to the `.env` defaults, set `BOT_DEFAULT_SUPABASE_*` variables (see below) before collecting user input.
5. Ensure `pgvector` and Supabase pools are provisioned; see `Vector Schema Strategy` for per-user migration rules.

Multi-Tenant Credential Storage
-------------------------------
Models in the `bot` app capture Telegram identities and secrets:

* `UserProfile`
  - `id`: AutoField.
  - `telegram_chat_id`: BigInteger, unique, indexed.
  - `telegram_username`: CharField, nullable (Telegram users may not have usernames).
  - `phone_number_e164`: CharField, validated and normalised.
  - `display_name`: CharField, optional alias shown in dashboards.
  - `onboarding_completed`: Boolean.
  - Timestamps: `created_at`, `updated_at`.
* `UserCredential` (OneToOne with `UserProfile`)
  - `supabase_project_id`: CharField (e.g., `rpxvoqzbjvsthzxmvqrc`).
  - `vector_db_host`: CharField.
  - `vector_db_port`: PositiveIntegerField.
  - `vector_db_name`: CharField.
  - `vector_db_user`: CharField.
  - `vector_db_password`: EncryptedTextField.
  - `supabase_rest_url`: URLField (optional, for REST API fallback).
  - `supabase_service_role`: EncryptedTextField (if supplied; otherwise anon key).
  - `openai_api_key`: EncryptedTextField.
  - `vector_schema_name`: CharField (defaults to `n8n_embed_<profile_id>`).
  - `last_validated_at`: DateTimeField.
  - Timestamps: `created_at`, `updated_at`.

Sensitive columns use Fernet-backed encrypted fields. Add `django-fernet-fields` (or `django-cryptography`) to `INSTALLED_APPS` and configure the secret via `FERNET_SECRET`.

Store encrypted material only after validation succeeds. A companion table `UserValidationEvent` can record failed attempts (reason, timestamp) to help operators debug user issues without revealing credentials.

Startup and Onboarding Flow
---------------------------
1. **Bot Startup** (first message or `/start`):
   - Send an informational banner (Russian copy by default, stored in locale files). Example placeholder: `"Privet! Etot bot vypolniaet GPT-embedding dokumentov v Supabase. Vvedite dannye dlia podkliucheniia, chtoby prodolzhit'."`
   - Look up `UserProfile` by `telegram_chat_id`. If found and `onboarding_completed` is true, proceed directly to ingestion handlers; otherwise re-run onboarding.
2. **Onboarding Wizard** (conversation state machine):
   - Prompt sequentially for each required datum. Suggested order mirrors `.env` keys:
     1. Telegram phone number (ensure user shares contact or manual entry).
     2. Supabase project identifier or host (e.g., `aws-1-us-east-1.pooler.supabase.com`).
     3. Vector database name.
     4. Vector database user (service role).
     5. Vector database password.
     6. Vector database host (pre-fill from project host if identical).
     7. Vector database port (default 5432; allow skip to accept default).
     8. Supabase service-role or anon key for REST (optional but recommended).
     9. Supabase REST URL (allow auto-generation from project id).
     10. OpenAI API key.
     11. Optional: vector schema/table name suffix (default generated).
   - After each response run validation (see below). If validation fails, send an error message and re-ask the same field; never advance while invalid.
   - Cache interim answers in conversation data; do not persist until the whole bundle is valid.
3. **Validation Pipeline** (executed once all fields collected or on field-by-field basis):
   - `phone_number`: normalise to E.164 using `phonenumbers`.
   - `supabase_host`: parse via `urllib.parse`; ensure domain ends with `.supabase.co`.
   - `port`: cast to int; require `0 < port < 65536`.
   - `credentials`: attempt a read-only `SELECT 1` against the vector database using `psycopg` with `connect_timeout=5`.
   - `supabase_rest_url`: perform a lightweight `GET /rest/v1/` request with the provided key (expect 200/401). Surface clear guidance if authentication fails.
   - `schema`: check for existing vector extension (`SELECT 1 FROM pg_extension WHERE extname='vector'`); if missing, return actionable error.
   - `openai_api_key`: call `client.embeddings.create(model='text-embedding-3-small', input='ping')`. If an error occurs, inspect status code; show human-readable hints (401 -> invalid key, 429 -> wait).
4. **Post-Validation Actions**:
   - Persist `UserProfile` and `UserCredential` within a transaction.
   - Store a hashed version of the OpenAI key fingerprint (`hashlib.sha256`) to detect key changes later.
   - Mark `onboarding_completed=True`.
   - Trigger per-user vector schema migration (next section).
   - Send success message and expose the standard command menu.
5. **Retry Loop**:
   - On connection failures, explain the error and offer `/retry_setup` command to restart the wizard. Preserve partial answers only if the user confirms reuse.

Vector Schema Strategy
----------------------
Each Supabase credential pair gets an isolated embedding table. Use deterministic naming (`n8n_embed_<profile_id>`) to avoid collisions. Implementation outline:

1. After onboarding, register a new Django database alias for the user:
   ```python
   connections.databases[f"user_{profile.id}_vectors"] = {
       "ENGINE": "django.db.backends.postgresql",
       "NAME": cred.vector_db_name,
       "USER": cred.vector_db_user,
       "PASSWORD": cred.vector_db_password_decrypted,
       "HOST": cred.vector_db_host,
       "PORT": cred.vector_db_port,
       "OPTIONS": {"sslmode": "require"},
   }
   ```
2. Create a migration helper `ensure_vector_schema(profile)` that:
   - Connects to the alias.
   - Enables `vector` extension if missing (`CREATE EXTENSION IF NOT EXISTS vector;`).
   - Executes a safe `CREATE TABLE IF NOT EXISTS` statement for `vector_schema_name` with a `vector(1536)` column, plus indexes on `(chat_id, file_name)`.
   - Records completion in `UserCredential.last_validated_at`.
3. Persist a migration artifact per user by storing the target schema name in `UserCredential`. This allows later migrations (e.g., column changes) to iterate over all registered schemas.

If Supabase responds with `UndefinedTable` during ingestion, follow the recovery checklist below before retrying.

UndefinedTable Recovery Checklist
---------------------------------
```
1. Stop the bot worker.
2. Remove generated migrations in apps involved in Supabase state (keep `__init__.py`):
   rm ingestion/migrations/00*.py
3. Truncate Django migration history for the affected app on Supabase:
   delete from django_migrations where app='ingestion';
4. Recreate migrations locally:
   python manage.py makemigrations ingestion
5. Re-run migrations against Supabase using the user's alias:
   python manage.py migrate --database user_<profile_id>_vectors ingestion
6. Call ensure_vector_schema(profile) to recreate the embedding table.
7. Restart the bot and repeat onboarding validation to confirm connectivity.
```
Automate steps 2-6 via a management command (`python manage.py reset_vector_schema <profile_chat_id>`) that warns users about data loss.

Embedding Workflow
------------------
The LangGraph agent (`embeddings/agent.py`) continues to orchestrate batch embedding calls:

* The embedding client is initialised with the per-user OpenAI key fetched from `UserCredential`.
* Default model remains `text-embedding-3-small` (1536-dimensional vectors).
* Retry policy: up to six attempts with exponential backoff; log and bubble unrecoverable errors to notify the operator and suspend the file job.
* Batch size (`SEGMENT_BATCH_SIZE=10`) and sleep windows (`request_delay=2s`) remain tunable via settings or per-user overrides stored in the profile.

During ingestion the workflow uses the dynamic database alias to write into the user's Supabase table. A `VectorStoreService` wrapper should encapsulate insert/delete logic and take `profile` as input, ensuring that multi-tenant writes never cross accounts.

Implementation Roadmap
----------------------
1. **Model Layer**
   - Add `bot` models (`UserProfile`, `UserCredential`, `UserValidationEvent`).
   - Integrate encrypted fields and migrations.
2. **Configuration**
   - Extend settings with `FERNET_SECRET` and helper to register per-user database aliases.
   - Introduce `BOT_DEFAULT_SUPABASE_*` fallback settings for demo environments.
3. **Bot Onboarding Wizard**
   - Build a `ConversationHandler` with explicit states per field.
   - Add validators powered by Pydantic; surface precise errors.
   - Persist successful onboarding and trigger schema creation.
4. **Vector Store Abstraction**
   - Implement `VectorSchemaService` (`ensure_vector_schema`, `reset_vector_schema`, `list_vector_tables`).
   - Update ingestion pipeline to accept `profile` and route to the correct alias.
5. **Error Handling**
   - Catch `UndefinedTable` and map to actionable Telegram responses (offer `/reset_supabase` command).
   - Implement the management command for schema resets.
6. **Testing**
   - Add unit tests for validators, schema creation, onboarding conversation.
   - Add integration tests using a temporary Postgres container to mimic Supabase.
   - Mock OpenAI calls to keep tests deterministic.
7. **Documentation and Ops**
   - Ship operator guides for onboarding support, credential rotation, and schema resets.
   - Add observability hooks (structured logs with profile id, tracing context).

Testing Checklist
-----------------
* Onboarding wizard: multiple happy paths and failure scenarios (invalid host, wrong OpenAI key, revoked Supabase password).
* Credential persistence: ensure encryption, decryption, and hashing behave as expected.
* Schema provisioning: verify tables are created with correct pgvector dimension and indexes.
* Ingestion flow: confirm per-user alias isolation by uploading files from two Telegram accounts.
* Error recovery: simulate `UndefinedTable` and confirm the management command regenerates the schema.
* Regression: existing segmentation, embedding, and export flows still succeed once onboarding is complete.

Operational Notes
-----------------
* Rotate OpenAI and Supabase credentials per user; provide `/rotate_keys` command that re-runs validation.
* Log onboarding failures with anonymised context only; never log secrets.
* Rate-limit onboarding attempts to mitigate brute-force of credential prompts.
* When revoking Supabase credentials, run the reset management command to drop orphan tables.
* Back up the local Django database; it now contains the source of truth for all users and secrets.
