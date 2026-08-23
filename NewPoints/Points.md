# 🚀 Agnostic AI Backend Base — Full Project Plan

> **Version:** 1.1
> **Status:** Planning Complete ✅
> **Last Updated:** 2026-08-02
> **Estimated Duration:** 4-6 weeks

---

## 📑 Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack](#2-tech-stack)
3. [Full System Architecture](#3-full-system-architecture)
4. [Directory Structure](#4-directory-structure)
5. [Component Interaction Map](#5-component-interaction-map)
6. [API Endpoints Inventory](#6-api-endpoints-inventory)
7. [User Journey Lifecycle](#7-user-journey-lifecycle)
8. [Data Lifecycle](#8-data-lifecycle)
9. [Request Lifecycle](#9-request-lifecycle)
10. [Application Startup Lifecycle](#10-application-startup-lifecycle)
11. [Application Shutdown Lifecycle](#11-application-shutdown-lifecycle)
12. [Development Roadmap](#12-development-roadmap)
13. [Observability Plan](#13-observability-plan)
14. [Metrics Inventory](#14-metrics-inventory)
15. [Container Inventory](#15-container-inventory)
16. [Summary](#16-summary)

---

## 1. Project Overview

### 🎯 Purpose
An **agnostic AI backend base** — a reusable foundation for building AI-powered services with production-grade infrastructure. This base app provides **no domain-specific business logic** (no PDF processing, no embeddings pipeline, etc.); instead, it ships the plumbing needed to plug in any AI workflow later:

- **Authentication** (JWT + Google OAuth token-based)
- **Async Task Processing** (Celery + RabbitMQ broker + Redis results backend)
- **Caching Layer** (Redis)
- **Reverse Proxy** (Nginx)
- **Observability** (Prometheus + Grafana) — *future phase*

> ⚠️ **Change from v1.0:** All domain services (Arabic PDF processing, embeddings, generation, document engines) have been **removed** from this base. Consumers of this base will add their own services on top.

### ✅ Design Principles
- Preserve existing **async factory pattern** (`init_class`, `init_service`)
- Preserve **interface segregation** (Base interfaces + providers)
- Preserve **registry-based factories** where infrastructure is pluggable
- **Provider-agnostic** — easy to swap databases, brokers, cache engines, etc.
- **Clean Architecture** — Api → Services → Infrastructure
- **Domain-free base** — no business services shipped; only infrastructure & auth

---

## 2. Tech Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Edge / Gateway** | Nginx | SSL, rate limit, load balance |
| **API Framework** | FastAPI | Async HTTP handlers |
| **Authentication** | PyJWT + google-auth | JWT + Google OAuth verification |
| **Message Broker** | RabbitMQ | Celery broker (task queue) |
| **Task Queue** | Celery | Async background jobs |
| **Results Backend** | Redis | Celery task results storage |
| **Cache** | Redis | JWT blocklist, rate limits |
| **Document DB** | MongoDB | Users, jobs metadata |
| **Vector DB** | Qdrant | Reserved for consumer apps |
| **Container** | Docker + Docker Compose | Deployment |
| **Monitoring** 🔮 | Prometheus + Grafana | Metrics & dashboards |

> 💡 **Broker/Backend split:** RabbitMQ = **broker** (durable, reliable task delivery). Redis = **results backend** (fast key/value lookups for task status & results).

---

## 3. Full System Architecture

```
╔══════════════════════════════════════════════════════════════════════╗
║                         🌍 EXTERNAL WORLD                            ║
║   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐       ║
║   │ Browser  │    │  Mobile  │    │ Postman  │    │  Google  │       ║
║   └────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘       ║
╚════════╪═══════════════╪═══════════════╪═══════════════╪═════════════╝
         └───────────────┴───────┬───────┘               │
                                 │ HTTPS                 │
                                 ▼                       │
╔══════════════════════════════════════════════════════════════════════╗
║                      🌐 EDGE LAYER (NGINX)                           ║
║  ┌────────────────────────────────────────────────────────────────┐  ║
║  │  SSL │ Rate Limit │ Load Balance │ Compression │ /metrics 📊   │  ║
║  └────────────────────────┬───────────────────────────────────────┘  ║
╚═══════════════════════════╪══════════════════════════════════════════╝
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
╔══════════════════════════════════════════════════════════════════════╗
║              🚀 APPLICATION LAYER (FastAPI)                          ║
║  ┌──────────┐   ┌──────────┐   ┌──────────┐                          ║
║  │ FastAPI  │   │ FastAPI  │   │ FastAPI  │                          ║
║  │ Worker 1 │   │ Worker 2 │   │ Worker N │                          ║
║  └────┬─────┘   └────┬─────┘   └────┬─────┘                          ║
║       └──────────────┼───────────────┘                               ║
║                      ▼                                               ║
║  ┌─────────────────────────────────────────────────┐                 ║
║  │ MIDDLEWARE: CORS→Auth→RateLimit→Log→Error       │                 ║
║  ├─────────────────────────────────────────────────┤                 ║
║  │ ROUTES: 🟢 Public | 🔐 Auth | 🔒 Protected      │                 ║
║  ├─────────────────────────────────────────────────┤                 ║
║  │ DEPENDENCIES: DI Container                      │                 ║
║  ├─────────────────────────────────────────────────┤                 ║
║  │ SERVICES: Auth | Welcome | Job                  │                 ║
║  │ (No domain services — add your own)             │                 ║
║  └───────┬─────────────────────────┬───────────────┘                 ║
╚══════════╪═════════════════════════╪═════════════════════════════════╝
           │                         │ enqueue jobs
           │                         ▼
           │            ╔════════════════════════════════════╗
           │            ║   📨 CELERY BROKER (RabbitMQ)      ║
           │            ║  ┌──────────────────────────────┐  ║
           │            ║  │ Queue: default               │  ║
           │            ║  │ Queue: dead_letter           │  ║
           │            ║  └──────────────────────────────┘  ║
           │            ╚═════════════╪══════════════════════╝
           │                          │
           │            ┌─────────────┼─────────────┐
           │            ▼             ▼             ▼
           │  ╔══════════════════════════════════════════════╗
           │  ║       ⚙️ WORKER LAYER (Celery)              ║
           │  ║  ┌──────────┐  ┌──────────┐  ┌──────────┐   ║
           │  ║  │ Worker 1 │  │ Worker 2 │  │ Worker N │   ║
           │  ║  └────┬─────┘  └────┬─────┘  └────┬─────┘   ║
           │  ║       └─────────────┼─────────────┘         ║
           │  ║  Base task interface (extend per project)   ║
           │  ╚═════════════════════╪══════════════════════╝
           │                        │
           │       ┌────────────────┼──────────────┐
           │       │                │              │
           │       ▼                ▼              ▼
           │  ┌────────┐      ┌──────────┐   ┌──────────┐
           │  │ Mongo  │      │ Redis    │   │ Qdrant   │
           │  │ jobs   │      │ results  │   │ (opt.)   │
           │  └────────┘      └──────────┘   └──────────┘
           │
           ▼
╔══════════════════════════════════════════════════════════════════════╗
║                       💾 DATA LAYER                                  ║
║ ┌──────────┐  ┌──────────┐  ┌──────────────────────────────────┐    ║
║ │ MongoDB  │  │  Qdrant  │  │  Redis                           │    ║
║ │ users 🆕 │  │ vectors  │  │  • JWT blocklist 🆕              │    ║
║ │ jobs 🆕  │  │ (avail.) │  │  • Rate limits 🆕                │    ║
║ │          │  │          │  │  • Celery results backend 🆕     │    ║
║ └──────────┘  └──────────┘  └──────────────────────────────────┘    ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
                              │ (Phase 7 - Future)
                              ▼
╔══════════════════════════════════════════════════════════════════════╗
║             📊 OBSERVABILITY LAYER (FUTURE PHASE 7)                 ║
║   ┌────────────────────────────────────────────────────────────┐    ║
║   │  🎯 PROMETHEUS  ←  scrapes metrics every 15s               │    ║
║   └────────────────────────┬───────────────────────────────────┘    ║
║                            ▼                                        ║
║   ┌────────────────────────────────────────────────────────────┐    ║
║   │  📈 GRAFANA     ←  dashboards + alerts                     │    ║
║   └────────────────────────────────────────────────────────────┘    ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## 4. Directory Structure

### Legend
- ✅ **UNCHANGED** — Keep as-is
- ✏️ **MODIFIED** — Small edits needed
- 🆕 **NEW** — Create from scratch
- ❌ **REMOVED** — Deleted from base (was domain-specific)
- 🔮 **FUTURE** — Reserved for Phase 7

```
📦 project-root/
 ┃
 ┣ 📂 src/
 ┃  ┃
 ┃  ┣ 📂 Api/                                    ✏️ EXTENDED
 ┃  ┃  ┣ 📂 ApiConfiguration/
 ┃  ┃  ┃  ┣ 📜 api_setting.py                    ✏️ +JWT +OAuth +Celery +Redis
 ┃  ┃  ┃  ┗ 📜 fast_api_config.py                ✏️ +middleware registration
 ┃  ┃  ┣ 📂 Middleware/                          🆕
 ┃  ┃  ┃  ┣ 📜 auth_middleware.py                🆕 JWT verify
 ┃  ┃  ┃  ┣ 📜 rate_limit_middleware.py          🆕 Redis-backed
 ┃  ┃  ┃  ┗ 📜 metrics_middleware.py             🔮 Prometheus
 ┃  ┃  ┗ 📂 Routes/
 ┃  ┃     ┣ 📂 Auth/                             🆕
 ┃  ┃     ┃  ┣ 📜 jwt_auth_routes.py             🆕 /register /login /refresh
 ┃  ┃     ┃  ┗ 📜 google_oauth_routes.py         🆕 /auth/google
 ┃  ┃     ┣ 📂 Client/
 ┃  ┃     ┃  ┣ 📜 welcome_routes.py              ✅ base welcome
 ┃  ┃     ┃  ┗ 📜 job_routes.py                  🆕 /jobs/{id}/status
 ┃  ┃     ┗ 📂 Monitoring/                       🔮
 ┃  ┃        ┗ 📜 metrics_routes.py              🔮 /metrics endpoint
 ┃  ┃
 ┃  ┣ 📂 Authentication/                         🆕 NEW MODULE
 ┃  ┃  ┣ 📜 auth_interface.py                    🆕
 ┃  ┃  ┣ 📂 Providers/
 ┃  ┃  ┃  ┣ 📜 jwt_provider.py                   🆕
 ┃  ┃  ┃  ┗ 📜 google_oauth_provider.py          🆕
 ┃  ┃  ┣ 📂 Schema/
 ┃  ┃  ┃  ┣ 📜 token_schema.py                   🆕
 ┃  ┃  ┃  ┗ 📜 user_schema.py                    🆕
 ┃  ┃  ┗ 📂 Exceptions/
 ┃  ┃     ┗ 📜 auth_exceptions.py                🆕
 ┃  ┃
 ┃  ┣ 📂 BackgroundTasks/                        🆕 NEW MODULE
 ┃  ┃  ┣ 📜 celery_app.py                        🆕 broker=RabbitMQ
 ┃  ┃  ┣ 📜 celery_config.py                     🆕 backend=Redis
 ┃  ┃  ┣ 📂 Tasks/
 ┃  ┃  ┃  ┗ 📜 task_interface.py                 🆕 base task class only
 ┃  ┃  ┗ 📂 Schema/
 ┃  ┃     ┗ 📜 job_schema.py                     🆕 JobStatus, JobResult
 ┃  ┃
 ┃  ┣ 📂 CacheInfrastructure/                    🆕 NEW MODULE
 ┃  ┃  ┣ 📜 cache_interface.py                   🆕
 ┃  ┃  ┗ 📂 Providers/
 ┃  ┃     ┗ 📂 Redis/
 ┃  ┃        ┗ 📜 redis_provider.py              🆕
 ┃  ┃
 ┃  ┣ 📂 Observability/                          🔮 FUTURE MODULE
 ┃  ┃  ┣ 📜 observability_interface.py           🔮
 ┃  ┃  ┣ 📂 Providers/
 ┃  ┃  ┃  ┗ 📜 prometheus_provider.py            🔮
 ┃  ┃  ┣ 📂 Metrics/
 ┃  ┃  ┃  ┣ 📜 api_metrics.py                    🔮
 ┃  ┃  ┃  ┗ 📜 celery_metrics.py                 🔮
 ┃  ┃  ┗ 📂 Schema/
 ┃  ┃     ┗ 📜 metric_schema.py                  🔮
 ┃  ┃
 ┃  ┣ 📂 DatabaseInfrastructure/                 ✅ UNCHANGED structure
 ┃  ┃  ┣ 📂 Json/
 ┃  ┃  ┃  ┣ 📂 Mongodb/
 ┃  ┃  ┃  ┃  ┣ 📜 async_controller.py
 ┃  ┃  ┃  ┃  ┗ 📜 Constants.py
 ┃  ┃  ┃  ┗ 📜 json_interface.py
 ┃  ┃  ┗ 📂 Vector/
 ┃  ┃     ┣ 📂 Providers/Qdrant/
 ┃  ┃     ┃  ┗ 📜 qdrant_provider.py
 ┃  ┃     ┣ 📂 Schema/
 ┃  ┃     ┃  ┗ 📜 vector_document.py
 ┃  ┃     ┗ 📜 vector_database_interface.py
 ┃  ┃
 ┃  ┣ 📂 Dependencies/                           ✏️ EXTENDED
 ┃  ┃  ┣ 📜 welcome_dependency.py                ✅
 ┃  ┃  ┣ 📜 auth_dependency.py                   🆕
 ┃  ┃  ┣ 📜 celery_dependency.py                 🆕
 ┃  ┃  ┗ 📜 redis_dependency.py                  🆕
 ┃  ┃  ┗ 📜 arabic_pdf_processing_dependency.py  ❌ REMOVED
 ┃  ┃
 ┃  ┣ 📂 Document/                               ❌ REMOVED (domain-specific)
 ┃  ┃                                            (was PDF engines & factories)
 ┃  ┃
 ┃  ┣ 📂 LLM/                                    ❌ REMOVED (domain-specific)
 ┃  ┃                                            (was Embedding & Generation)
 ┃  ┃
 ┃  ┣ 📂 Services/                               ✏️ EXTENDED (base only)
 ┃  ┃  ┣ 📂 Exceptions/
 ┃  ┃  ┃  ┗ 📜 auth_exceptions.py                🆕
 ┃  ┃  ┃  ┗ 📜 arabic_pdf_processing_excp.py     ❌ REMOVED
 ┃  ┃  ┣ 📂 Services/
 ┃  ┃  ┃  ┣ 📜 welcome_service.py                ✅
 ┃  ┃  ┃  ┣ 📜 auth_service.py                   🆕
 ┃  ┃  ┃  ┣ 📜 job_service.py                    🆕
 ┃  ┃  ┃  ┗ 📜 arabic_pdf_processing.py          ❌ REMOVED
 ┃  ┃  ┗ 📜 service_interface.py                 ✅ UNCHANGED
 ┃  ┃
 ┃  ┣ 📜 .env                                    ✏️ +new vars
 ┃  ┣ 📜 app.py                                  ✏️ +auth routes, middleware
 ┃  ┣ 📜 worker.py                               🆕 Celery entrypoint
 ┃  ┗ 📜 notebook.ipynb                          ❌ REMOVED (domain playground)
 ┃
 ┣ 📂 Deployment/                                🆕 NEW FOLDER
 ┃  ┣ 📂 Nginx/
 ┃  ┃  ┣ 📜 nginx.conf
 ┃  ┃  ┗ 📜 app.conf
 ┃  ┣ 📂 Docker/
 ┃  ┃  ┣ 📜 Dockerfile.api
 ┃  ┃  ┣ 📜 Dockerfile.worker
 ┃  ┃  ┗ 📜 .dockerignore
 ┃  ┣ 📂 Monitoring/                             🔮 FUTURE
 ┃  ┃  ┣ 📂 Prometheus/
 ┃  ┃  ┃  ┣ 📜 prometheus.yml
 ┃  ┃  ┃  ┗ 📂 rules/
 ┃  ┃  ┃     ┣ 📜 api_alerts.yml
 ┃  ┃  ┃     ┗ 📜 celery_alerts.yml
 ┃  ┃  ┗ 📂 Grafana/
 ┃  ┃     ┣ 📂 dashboards/
 ┃  ┃     ┃  ┣ 📜 api_health.json
 ┃  ┃     ┃  ┣ 📜 celery_jobs.json
 ┃  ┃     ┃  ┣ 📜 databases.json
 ┃  ┃     ┃  ┗ 📜 system.json
 ┃  ┃     ┗ 📂 provisioning/
 ┃  ┃        ┣ 📜 datasources.yml
 ┃  ┃        ┗ 📜 dashboards.yml
 ┃  ┗ 📜 docker-compose.yml
 ┃
 ┣ 📜 requirements.txt                           ✏️ +new deps, −domain deps
 ┣ 📜 PROJECT_PLAN.md                            🆕 THIS FILE
 ┗ 📜 README.md                                  ✏️
```

---

## 5. Component Interaction Map

```
╔══════════════════════════════════════════════════════════════════╗
║               WHO TALKS TO WHOM (Communication Map)              ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║   FROM              →   TO                    PURPOSE            ║
║   ──────────────────────────────────────────────────────────     ║
║   Client            →   Nginx                 HTTPS requests     ║
║   Nginx             →   FastAPI               HTTP proxy         ║
║   FastAPI           →   Google API            Verify ID token    ║
║   FastAPI           →   MongoDB               Users/Jobs CRUD    ║
║   FastAPI           →   Redis                 Token blocklist,   ║
║                                               Rate limits        ║
║   FastAPI           →   RabbitMQ              Enqueue Celery     ║
║                                               tasks (broker)     ║
║   FastAPI           →   Redis                 Read Celery task   ║
║                                               results (backend)  ║
║                                                                  ║
║   Celery Worker     →   RabbitMQ              Consume tasks      ║
║                                               (broker)           ║
║   Celery Worker     →   Redis                 Store task results ║
║                                               (backend)          ║
║   Celery Worker     →   MongoDB               Update job docs    ║
║                                                                  ║
║   Prometheus 🔮     →   All /metrics          Scrape metrics     ║
║   Grafana 🔮        →   Prometheus            Query metrics      ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 6. API Endpoints Inventory

```
┌──────────────────────────────────────────────────────────────────┐
│                     ENDPOINT INVENTORY                           │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  🟢 PUBLIC (no auth needed)                                      │
│  ─────────────────────────────                                   │
│  GET   /                          → Welcome                      │
│  GET   /health                    → Health check                 │
│  GET   /docs                      → Swagger UI                   │
│  GET   /metrics 🔮                → Prometheus metrics           │
│                                                                  │
│  🔐 AUTHENTICATION                                               │
│  ─────────────────────────────                                   │
│  POST  /auth/register             → Create user (email+pass)     │
│  POST  /auth/login                → Login → JWT pair             │
│  POST  /auth/google               → Verify Google ID token       │
│                                     → Issue JWT pair             │
│  POST  /auth/refresh              → New access token             │
│  POST  /auth/logout               → Blocklist token in Redis     │
│  GET   /auth/me                   → Current user info            │
│                                                                  │
│  🔒 PROTECTED (JWT required) — Base job endpoints                │
│  ─────────────────────────────                                   │
│  GET   /jobs/{id}/status          → Check Celery task status     │
│  GET   /jobs/{id}/result          → Fetch task result from Redis │
│  GET   /jobs                      → List user's jobs             │
│  DELETE /jobs/{id}                → Revoke/delete Celery task    │
│                                                                  │
│  📝 NOTE: Domain-specific endpoints (e.g. PDF upload) are        │
│      added by the consumer app on top of this base.              │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 7. User Journey Lifecycle

### Stage 1: Authentication (Google Token-Based)

```
  USER      FRONTEND      NGINX      FASTAPI      GOOGLE      MONGO
   │           │            │           │           │           │
   │ 1.Click   │            │           │           │           │
   │  Login    │            │           │           │           │
   │──────────▶│            │           │           │           │
   │           │ 2.Google SDK popup     │           │           │
   │           │────────────────────────────────────▶│           │
   │           │ 3.Google ID Token      │           │           │
   │           │◀────────────────────────────────────│           │
   │           │ 4.POST /auth/google    │           │           │
   │           │  {id_token}│           │           │           │
   │           │───────────▶│──────────▶│           │           │
   │           │            │           │ 5.Verify token        │
   │           │            │           │──────────▶│           │
   │           │            │           │◀──────────│           │
   │           │            │           │ 6.Upsert user         │
   │           │            │           │──────────────────────▶│
   │           │            │           │ 7.Generate JWT pair   │
   │           │ 8.{access, refresh}    │           │           │
   │           │◀───────────│◀──────────│           │           │
   │ ✅ Logged │            │           │           │           │
   │◀──────────│            │           │           │           │
```

### Stage 2: Generic Async Task Dispatch (base pattern)

```
  USER    FRONTEND    NGINX    FASTAPI    RABBITMQ    MONGO
   │         │          │         │          │          │
   │ Trigger │          │         │          │          │
   │────────▶│          │         │          │          │
   │         │ POST /<domain-route>          │         │
   │         │─────────▶│────────▶│          │         │
   │         │          │  Verify JWT        │         │
   │         │          │         │ Create Job doc    │
   │         │          │         │──────────────────▶│
   │         │          │         │ Enqueue task      │
   │         │          │         │─────────▶│        │
   │         │ {job_id, "queued"} │          │        │
   │         │◀─────────│◀────────│          │        │
   │ ✅ Job  │          │         │          │        │
   │◀────────│          │         │          │        │
```

### Stage 3: Background Processing (base task lifecycle)

```
  RABBITMQ       CELERY WORKER          REDIS         MONGO
     │                │                    │            │
     │ Pick task      │                    │            │
     │───────────────▶│                    │            │
     │                │ Status: STARTED    │            │
     │                │───────────────────▶│            │
     │                │ Update job doc               │
     │                │───────────────────────────────▶│
     │                │                    │            │
     │                │ ...run domain work...          │
     │                │                    │            │
     │                │ Store final result │            │
     │                │───────────────────▶│            │
     │                │ Status: SUCCESS                │
     │                │───────────────────────────────▶│
```

### Stage 4: Status Polling

```
  FRONTEND     NGINX     FASTAPI     REDIS      MONGO
     │           │          │          │          │
     │ GET /jobs/{id}/status│          │          │
     │──────────▶│─────────▶│          │          │
     │           │          │ Query Celery result│
     │           │          │─────────▶│          │
     │           │          │◀─────────│          │
     │           │          │ Get job metadata    │
     │           │          │─────────────────────▶│
     │           │          │◀─────────────────────│
     │ {status, progress}   │          │          │
     │◀──────────│◀─────────│          │          │
```

---

## 8. Data Lifecycle

```
     🚀 TASK TRIGGERED (by consumer route)
          │
          ▼
    ┌──────────────────┐
    │  Job Doc Created │  ← MongoDB: status=QUEUED, progress=0
    └────────┬─────────┘
             ▼
    ┌──────────────────┐
    │  RabbitMQ Msg    │  ← {job_id, payload, user_id}
    │  (broker)        │
    └────────┬─────────┘
             ▼
    ┌──────────────────┐
    │ Worker picks up  │  ← status=STARTED
    └────────┬─────────┘
             ▼
    ┌──────────────────────┐
    │  Domain work runs    │  ← progress updates via
    │  (consumer-defined)  │     update_state()
    └────────┬─────────────┘
             ▼
    ┌──────────────────────────────────┐
    │ Result stored in Redis (backend) │  ← TTL: 24h
    │ Job doc updated → SUCCESS/FAIL   │  ← MongoDB
    └──────────────────────────────────┘
```

---

## 9. Request Lifecycle

```
    📥 Client Request
         │
         ▼
   ┌──────────────────────┐
   │   NGINX RECEIVES     │
   │   • SSL decryption   │
   │   • Rate limit       │
   │   • Forward upstream │
   └──────────┬───────────┘
              ▼
   ┌─────────────────────────────────────────┐
   │      FASTAPI MIDDLEWARE PIPELINE        │
   │  1️⃣  CORS                              │
   │  2️⃣  Request Logger                    │
   │  3️⃣  Auth Middleware (JWT)             │
   │  4️⃣  Rate Limit (Redis)                │
   │  5️⃣  Route Handler                     │
   │  6️⃣  Error Handler                     │
   └───────────────┬─────────────────────────┘
                   ▼
              📤 Response
                   │
                   ▼
   ┌──────────────────────┐
   │  NGINX RESPONDS      │
   └──────────┬───────────┘
              ▼
         📱 Client
```

---

## 10. Application Startup Lifecycle

```
  ┌──────────────────────┐
  │  🐳 Docker Compose   │
  └──────────┬───────────┘
             ▼
  ┌──────────────────────────────────────┐
  │  Infrastructure services             │
  │  1. MongoDB                          │
  │  2. Qdrant                           │
  │  3. Redis      (cache + Celery bkd)  │
  │  4. RabbitMQ   (Celery broker)       │
  └──────────┬───────────────────────────┘
             │ (health checks ✓)
             ▼
  ┌──────────────────────────────────────┐
  │  Application services                │
  │  5. FastAPI (uvicorn)                │
  │  6. Celery Workers                   │
  │  7. Nginx                            │
  └──────────┬───────────────────────────┘
             ▼
  ┌──────────────────────────────────────┐
  │  FASTAPI LIFESPAN                    │
  │    ├─ Load settings                  │
  │    ├─ Init Mongo/Qdrant/Redis        │
  │    ├─ Init Celery client             │
  │    │    (broker=RabbitMQ,            │
  │    │     backend=Redis)              │
  │    └─ Store in app.state             │
  │  ✅ Ready to serve                   │
  └──────────────────────────────────────┘
```

---

## 11. Application Shutdown Lifecycle

```
  🛑 SIGTERM received
         │
         ▼
  ┌──────────────────────────────────┐
  │  NGINX: Drain connections        │
  └──────────┬───────────────────────┘
             ▼
  ┌──────────────────────────────────┐
  │  FASTAPI Lifespan Shutdown       │
  │  ├─ Finish in-flight requests    │
  │  ├─ Close DB connections         │
  │  └─ Log shutdown                 │
  └──────────┬───────────────────────┘
             ▼
  ┌──────────────────────────────────┐
  │  CELERY Workers                  │
  │  ├─ Stop consuming new tasks     │
  │  ├─ Finish current task          │
  │  └─ Close connections            │
  └──────────┬───────────────────────┘
             ▼
  ┌──────────────────────────────────┐
  │  Infrastructure persists data    │
  └──────────────────────────────────┘
```

---

## 12. Development Roadmap

### 📋 PHASE 0: PLANNING & CLEANUP ✅ COMPLETE
- Architecture diagrams
- Data flow definitions
- API contracts
- Tech stack finalization
- **Remove domain modules** (Document, LLM, Arabic PDF service, notebook)
- **Duration:** 1-2 days

---

### 🔐 PHASE 1: AUTHENTICATION LAYER
| Step | Task |
|------|------|
| 1.1  | Extend `api_setting.py` (JWT/OAuth vars) |
| 1.2  | Build Authentication module skeleton |
| 1.3  | JWT Provider (create/verify/refresh) |
| 1.4  | Google OAuth Provider (verify ID token) |
| 1.5  | User schemas & Mongo collection |
| 1.6  | `AuthService` (register/login) |
| 1.7  | Auth routes (`/register`, `/login`, `/google`, `/refresh`) |
| 1.8  | `auth_dependency` (`get_current_user`) |
| 1.9  | Protect base routes |
| 1.10 | Test with Postman + Google Playground |

**Duration:** 3-5 days

---

### 💾 PHASE 2: CACHE INFRASTRUCTURE (Redis)
| Step | Task |
|------|------|
| 2.1  | `CacheInfrastructure` module |
| 2.2  | `RedisProvider` (async connection pool) |
| 2.3  | JWT blocklist integration (logout) |
| 2.4  | Rate limiting middleware |
| 2.5  | Redis dependency injection |

**Duration:** 1-2 days

---

### ⚙️ PHASE 3: ASYNC TASKS (Celery + RabbitMQ + Redis)
| Step | Task |
|------|------|
| 3.1  | Setup Celery app & config |
| 3.2  | **Broker = RabbitMQ**, **Backend = Redis** |
| 3.3  | `task_interface` (base async task class only, no domain tasks) |
| 3.4  | Job schema (JobStatus enum, JobResult) |
| 3.5  | `JobService` (status/result queries via Celery + Mongo) |
| 3.6  | Generic job status/result routes |
| 3.7  | `worker.py` entrypoint |
| 3.8  | End-to-end test with a dummy task |

**Duration:** 3-5 days

---

### 🚢 PHASE 4: CONTAINERIZATION & NGINX
| Step | Task |
|------|------|
| 4.1  | `Dockerfile.api` (FastAPI image) |
| 4.2  | `Dockerfile.worker` (Celery image) |
| 4.3  | `nginx.conf` (proxy + SSL + rate limit) |
| 4.4  | `docker-compose.yml` (7 services) |
| 4.5  | Environment separation (dev/staging/prod) |
| 4.6  | Health check endpoints |

**Duration:** 2-3 days

---

### 🧪 PHASE 5: TESTING & HARDENING
| Step | Task |
|------|------|
| 5.1  | Unit tests (auth service, providers, cache) |
| 5.2  | Integration tests (auth flow, dummy job flow) |
| 5.3  | Load testing (concurrent auth + task dispatch) |
| 5.4  | Security audit (JWT, injection, XSS) |
| 5.5  | API documentation |

**Duration:** 3-5 days

---

### 🚀 PHASE 6: DEPLOYMENT
| Step | Task |
|------|------|
| 6.1  | Deploy to staging |
| 6.2  | Monitor logs, errors, performance |
| 6.3  | Setup alerts |
| 6.4  | Deploy to production |
| 6.5  | Post-deployment smoke tests |

**Duration:** 2-3 days

---

### 📊 PHASE 7: OBSERVABILITY (Prometheus + Grafana) 🔮
| Step | Task |
|------|------|
| 7.1  | Add `prometheus-client` to FastAPI |
| 7.2  | Create Observability module |
| 7.3  | Instrument API metrics (RED method) |
| 7.4  | Instrument Celery metrics |
| 7.5  | Setup exporters (mongo, redis, node) |
| 7.6  | Prometheus config + alert rules |
| 7.7  | Grafana dashboards |
| 7.8  | Alert notifications (Slack/Email) |
| 7.9  | Load test to validate dashboards |

**Duration:** 4-6 days

---

### 📊 TOTAL ESTIMATED TIME: **19-31 days (4-6 weeks)**

---

## 13. Observability Plan

### 🎯 Prometheus
- Scrapes `/metrics` endpoints every 15s
- Time-series database (15-day retention)
- Alert rules engine

### 📈 Grafana Dashboards

| Dashboard | Metrics |
|-----------|---------|
| 🚀 **API Health** | RPS, Latency p99, Error rate |
| ⚙️ **Celery Jobs** | Task rate, Success/Fail, Queue depth |
| 💾 **Databases** | Mongo ops, Qdrant search, Redis memory |
| 🔐 **Auth** | Login rate, Failed auths, Tokens issued |
| 🖥 **System** | CPU, RAM, Disk, Network I/O |

> 📝 Domain-specific dashboards (e.g., PDF pipeline) are added by consumer apps.

---

## 14. Metrics Inventory

### 🚀 API Metrics (RED Method)
| Metric | Type |
|--------|------|
| `http_requests_total{method, path, status}` | Counter |
| `http_request_duration_seconds{path}` | Histogram |
| `http_requests_in_progress` | Gauge |

### 🔐 Auth Metrics
| Metric | Type |
|--------|------|
| `auth_login_attempts_total{provider, status}` | Counter |
| `auth_tokens_issued_total{type}` | Counter |
| `auth_blocklist_size` | Gauge |

### ⚙️ Celery Metrics
| Metric | Type |
|--------|------|
| `celery_task_total{name, status}` | Counter |
| `celery_task_duration_seconds{name}` | Histogram |
| `celery_queue_length{queue}` | Gauge |
| `celery_workers_active` | Gauge |

### 💾 Infrastructure Metrics
| Metric | Type |
|--------|------|
| `mongodb_connections_active` | Gauge |
| `redis_memory_used_bytes` | Gauge |
| `rabbitmq_queue_messages{queue}` | Gauge |
| `qdrant_search_duration_seconds` | Histogram |

> 📝 Business/domain metrics are added by consumer apps.

---

## 15. Container Inventory

### Core Services (Phases 1-4)
| # | Service | Purpose |
|---|---------|---------|
| 1 | `nginx` | Reverse proxy |
| 2 | `fastapi` | API server |
| 3 | `celery-worker` | Background tasks |
| 4 | `mongodb` | Metadata store |
| 5 | `qdrant` | Vector store (available for consumers) |
| 6 | `redis` | Cache + **Celery results backend** |
| 7 | `rabbitmq` | **Celery broker** |

### Observability Services (Phase 7) 🔮
| # | Service | Purpose |
|---|---------|---------|
| 8 | `prometheus` | Metrics DB |
| 9 | `grafana` | Dashboards |
| 10 | `node-exporter` | Host metrics |
| 11 | `mongo-exporter` | MongoDB metrics |
| 12 | `redis-exporter` | Redis metrics |
| 13 | `cadvisor` | Container metrics (optional) |

**📊 Total: 7 initial → 13 final**

---

## 16. Summary

```
╔══════════════════════════════════════════════════════════════════╗
║                    ✅ FINAL PLAN SUMMARY (v1.1)                  ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  📦 NEW MODULES              ➜  5                                ║
║     • Authentication          (Phase 1)                          ║
║     • CacheInfrastructure     (Phase 2)                          ║
║     • BackgroundTasks         (Phase 3)                          ║
║     • Deployment              (Phase 4)                          ║
║     • Observability           (Phase 7) 🔮                       ║
║                                                                  ║
║  ❌ REMOVED MODULES           ➜  3                               ║
║     • Document (PDF engines & factories)                         ║
║     • LLM (Embedding & Generation)                               ║
║     • Arabic PDF service + its exceptions/deps/notebook          ║
║                                                                  ║
║  ✏️  MODIFIED FILES           ➜  ~6                              ║
║  🆕 NEW FILES                ➜  ~22                              ║
║  ✅ UNCHANGED MODULES         ➜  DatabaseInfrastructure,         ║
║                                 service_interface, welcome       ║
║                                                                  ║
║  🎯 TECH STACK                                                   ║
║     Auth:      JWT + Google OAuth (token-based)                  ║
║     Async:     Celery                                            ║
║       ├─ Broker:   RabbitMQ                                      ║
║       └─ Backend:  Redis                                         ║
║     Cache:     Redis                                             ║
║     Gateway:   Nginx                                             ║
║     Monitor:   Prometheus + Grafana 🔮                           ║
║                                                                  ║
║  🐳 CONTAINERS               ➜  7 initial → 13 final             ║
║                                                                  ║
║  ⏱  TIMELINE                 ➜  4-6 weeks total                  ║
║                                                                  ║
║  🎨 CODE STYLE               ➜  Preserves existing async         ║
║                                 factory pattern                  ║
║                                                                  ║
║  🧱 SCOPE                    ➜  AGNOSTIC BASE ONLY               ║
║                                 (no domain services shipped)     ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 🚀 Next Step

**Phase 0 cleanup:** Delete the `Document/`, `LLM/` folders, remove `arabic_pdf_processing.py`, its dependency, its exception file, and the `notebook.ipynb` playground. Then proceed to **Phase 1** — update `src/Api/ApiConfiguration/api_setting.py` to add JWT and Google OAuth configuration variables.

---

*Document maintained by the project team. Update this file as the project evolves.*