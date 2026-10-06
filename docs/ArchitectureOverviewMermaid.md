```mermaid
flowchart TB
    subgraph Clients["1. Presentation"]
        UI["Web UI — Firebase App Hosting
        Chat, Golden review, persona editing"]
        CLI["CLI — prototype"]
    end

    subgraph Edge["2. Edge — only public ingress"]
        BFF["BFF API
        Auth, request logging, routing"]
    end

    subgraph Application["3. Application — Cloud Run"]
        Backend["Chatbot backend
        Starlette + REST / SSE
        LangChain / LangGraph
        Bounded analysis loop"]
        Worker["Durable analysis worker
        Continues work after SSE disconnect"]
        Ingestion["Golden ingestion service
        Validate, chunk, embed, index"]
    end

    subgraph Messaging["4. Messaging"]
        PubSub["Google Cloud Pub/Sub"]
    end

    subgraph AI["5. Models — Vertex AI"]
        Chat["Gemini chatbot
        Default: gemini-3.8-flash
        Complex analysis: Pro"]
        Embedding["Gemini Embedding
        gemini-embedding-001"]
    end

    subgraph Data["6. Data sources and persistence"]
        BigQuery[("BigQuery
        Read-only retail dataset")]
        Postgres[("Cloud SQL — PostgreSQL + pgvector
        Conversations, reports, preferences
        Personas, entitlements, audit log
        Golden candidates and retrieval index")]
        Golden[("Initial Golden Dataset
        Data lake")]
        Storage[("Cloud Storage
        Report artifacts")]
    end

    subgraph Operations["7. Observability and evaluation"]
        LangSmith["LangSmith
        Sanitized traces, debugging, evaluations"]
        CloudLogging["GCP Cloud Logging
        Application logs (prod sink)"]
        Metrics["Prometheus metrics
        /metrics → Cloud Monitoring"]
    end

    UI -->|"HTTPS"| BFF
    CLI -->|"HTTPS"| BFF
    BFF -->|"Route + forward identity"| Backend
    Backend -->|"PII-checked SSE / JSON via BFF"| UI
    Backend -->|"PII-checked responses via BFF"| CLI
    Backend -->|"Enqueue / resume long runs"| Worker
    Worker -->|"Persist progress"| Postgres

    Backend -->|"Approved entry ID / version"| PubSub
    PubSub -->|"Ingestion event"| Ingestion

    Backend -->|"PII-safe prompts
    Bounded retries"| Chat
    Worker -->|"PII-safe prompts"| Chat
    Backend -->|"PII-safe query text"| Embedding
    Ingestion -->|"PII-safe Golden text"| Embedding

    Backend <-->|"Validated SQL / results
    Enforced product scope
    Bounded SQL repair"| BigQuery
    Worker <-->|"Validated SQL / results"| BigQuery

    Backend <-->|"Persist state
    Retrieve authorized Golden examples
    Load entitlements"| Postgres

    Golden -->|"Initial ingestion"| Ingestion
    Ingestion -->|"Store approved entries and vectors"| Postgres
    Backend <-->|"Save / retrieve artifacts"| Storage

    Backend -->|"PII-safe traces"| LangSmith
    Ingestion -->|"PII-safe ingestion traces"| LangSmith
    BFF -->|"Access / edge logs"| CloudLogging
    Backend -->|"Application logs"| CloudLogging
    Ingestion -->|"Application logs"| CloudLogging
    Backend -->|"Scrape /metrics"| Metrics
```
