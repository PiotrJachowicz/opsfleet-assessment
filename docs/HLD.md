# High-Level Design: Retail Data Analysis Chatbot

This document describes the **production** design for the retail data analysis assistant. Prototype setup and implementation are described in appropraite readme.md.

---

## 1. Purpose, scope, and assumptions

This system lets non-technical executives ask natural-language questions about sales, inventory, and performance, then receive evidence-based answers and reports. It combines a read-only analytical store with reviewed Golden set of analyst examples, and it must stay within product entitlements, refuse non-analytical work, and keep raw PII out of model inputs and released outputs.

**Features in scope:** 
- authenticated chat analysis,
- saved-report snapshots lifecycle with deletion confirmation,
- Golden set retrieval,
- Golden set candidates approval & addition,
- persona editing for authorized non-developers (single instance with change history)
- and the operational controls needed to run that in production.

**Out of scope, but possible future additions:**
- reusable report templates instead of stored snapshots,
- multiple selectable personas

**Assumptions:**
- users are entitled to a defined set of products/brands, stored as a user-to-entitlement mapping in PostgreSQL (for example user `brand-calvin` → brands `["Calvin Klein"]`; admin → all brands)
- BigQuery `thelook_ecommerce` tables `orders`, `order_items`, `products`, and `users` are the only analytical sources. 

---

## 2. Core user flows

### 2.1 Analysis request

An authenticated request resolves entitlements, loads conversation context, preferences, and the active persona, then decides whether the ask is in analytical or report-management scope.

The full agent turn is as follows:
- retrieve a small set of approved Golden Set examples,
- plan and generate SQL,
- SQL validation in deterministic application code,
- SQL execution on BigQuery,
- result inspection and possible bounded repairs
- writing an evidence-based answer that is PII-checked before stream or return.

Treat “plan → query → inspect → refine → report” as one logical workflow with budgets (tool calls, SQL repairs, tokens, turn deadline). Ambiguous business definitions get a clarification question, and claims of the chatbot should always be based on data, with proper provenance included.

Reports will be saved as HTML artifacts for ease of debugging and better results when it comes to LLM generation compared to PDF.

```mermaid
sequenceDiagram
    actor User
    participant UI as Web UI / CLI
    participant BFF as BFF API
    participant API as Chat backend
    participant PG as PostgreSQL
    participant Emb as Vertex embeddings
    participant LLM as Vertex Gemini
    participant BQ as BigQuery

    User->>UI: Question
    UI->>BFF: Authenticated request
    BFF->>API: Route + forward identity
    API->>PG: Entitlements, context, persona, preferences
    API->>API: Scope check / clarify if needed
    API->>Emb: Embed contextualized question
    API->>PG: Retrieve approved Golden examples
    API->>LLM: Plan and draft SQL
    API->>API: Validate, constrain, enforce product scope
    API->>BQ: Execute read-only query
    API->>API: Inspect and bounded repair if justified
    API->>LLM: Draft evidence-based answer
    API->>API: Output PII / policy check
    API-->>BFF: SSE progress + validated content
    BFF-->>UI: SSE stream
    API->>PG: Persist turn state and sanitized evidence
```

### 2.2 Confirmed report deletion

Report removal is a destructive action, and as such should be an application-controlled workflow. When the user requests to delete a report, the chatbot can resolve the report in question and should show an approval UI (frontend component shown via a tool call), which, upon approval, should call an HTTP endpoint to **hard-delete** the report: remove the PostgreSQL metadata row and permanently delete the Cloud Storage artifact (no soft-delete / tombstone). The agent should never have access to delete the report directly.

```mermaid
sequenceDiagram
    actor User
    participant UI as Web UI
    participant BFF as BFF API
    participant Agent as Chat agent tools
    participant API as Delete HTTP API
    participant PG as PostgreSQL
    participant GCS as Cloud Storage

    User->>UI: Delete request (natural language)
    UI->>BFF: Chat turn
    BFF->>Agent: Forward identity + message
    Agent->>PG: Resolve owned report IDs
    Agent-->>UI: Tool result — approval UI (preview, no delete)
    Note over Agent: Agent has no delete tool
    User->>UI: Explicit confirm in approval UI
    UI->>BFF: HTTP hard-delete (selected report IDs)
    BFF->>API: Authenticated delete
    API->>PG: Recheck ownership
    API->>PG: Hard-delete metadata rows
    API->>GCS: Hard-delete report artifacts
    API->>PG: Audit event
    API-->>BFF: Deletion result
    BFF-->>UI: Deletion result
```

### 2.3 Golden set and learning

Part of the analysis loop is deciding whether a given analysis topic is a good candidate for the Golden Set - so a report generated based on a question, together with it's SQL Query. When a candidate has been identified, it is saved in the PostgreSQL database and a dedicated UI is being shown to the user, similarly to report deletion confirmation. Once a candidate has been confirmed, it is being added to the Pub/Sub and subsequently ran through embedding and saved in pgVector, and the candidate status is changed to accepted. Ingestion implementation must provide idempotency and retries.

The candidate record includes the Question/SQL/Report trio as well as metadata such as used model, user, provenance. 

Once an entry has been retired (through a dedicated UI), it is dropped out of retrieval immediately, but history is kept.

At query time the Chatbot Service embeds a contextualized question with the same model and dimensions as the index, filters to approved and in-scope entries, retrieves a small budgeted set, and treats those examples as methodology — then generates fresh SQL under the same security controls. User preferences are stored with provenance and used as part of the context as well.

```mermaid
sequenceDiagram
    actor User
    participant UI as Web UI
    participant BFF as BFF API
    participant Chat as Chat backend
    participant PG as PostgreSQL
    participant Bus as Pub/Sub
    participant Ingest as Ingestion service
    participant Emb as Vertex embeddings

    User->>UI: Analysis that yields a strong trio
    UI->>BFF: Chat turn
    BFF->>Chat: Forward identity + message
    Chat->>PG: Persist Golden candidate (pending)
    Chat-->>UI: Tool result — approval UI (HITL)
    User->>UI: Confirm candidate (or reject)
    UI->>BFF: Confirm / approve candidate
    BFF->>Chat: Approval
    Chat->>PG: Mark accepted + immutable version
    Chat->>Bus: Publish entry ID + version
    Bus->>Ingest: Ingestion event
    Ingest->>PG: Reload and verify that version
    Ingest->>Emb: Embed PII-safe chunks
    Ingest->>PG: Upsert vectors and mark indexed
    Ingest-->>Bus: Ack

    Note over User,PG: Later — Admin UI can retire an entry (drop from retrieval, keep history)
```

### 2.4 Persona management

Authorized non-developers edit presentation and tone in the admin UI. PostgreSQL stores versions, author, timestamps, and which configuration is active for audit purposes. There is only one global persona active at any given time. The persona prompt is deprioritized so that it can only affect the tone, and not any other parts of the system prompt.

Each analysis records the persona version it used. 

---

## 3. Architecture and technology rationale

The general setup will be a Next.js web UI, connected to a BFF API, responsible for user authentication, request logging and routing to the proper service. This ensures proper separation of concerns as well as extensibility for the future.  BFF is the only service reachable from outside of the network.

Behind this BFF there will be two main services - the Chatbot service, which will hold majority of the logic for the user flows - orchestrating a bounded LangGraph analysis loop for the chatbot, Golden Set examples retrieval, persona injection, persisting user reports etc. The other service would be the Indexing Service, responsible for initial indexing of the Golden Set, as well as ongoing ingestion of new approved candidates. All backend services will be running Python/Starlette on Cloud Run.

Google Pub/Sub is used for queuing of the Golden Set items for indexing, Indexing Service drains this queue.

The Next.js web UI is hosted on **Firebase App Hosting** so the frontend stays in the same Google Cloud estate as Cloud Run, IAM, and the rest of the stack.

User report snapshot files will be persisted in Cloud Storage.

For agent observability, a managed LangSmith service is used for traces and evaluations.

Application logs use the standard Python ``logging`` API. In production, the sink is **GCP Cloud Logging** (Cloud Run / ops agent ingestion of structured stdout, or the Cloud Logging handler). The prototype uses a local rotating **file sink** under ``output/logs`` (gitignored) so developers can inspect turn/tool/error logs without cloud setup; swapping the sink does not require changing call sites.

Persistent storage is delivered via CloudSQL PostgreSQL database with pgvector for Golden Set embeddings.  

Cloud Run is the baseline compute choice because both the chat API and Golden ingestion are independently scalable HTTP or event-driven services with all durable state outside the process.

Kubernetes is a future option only if concrete requirements (custom networking, sidecars, multi-service scheduling) justify the operational overhead.  This option should be kept in mind during implementation.

Vertex API is chosen as a Gemini production offering, due to alignment with other GCP services we are using, IAM integration and service accounts, ops alignment and enterprise data handling.

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

**Model strategy:** Default chat model ID is **`gemini-3.8-flash`** (same as the prototype) as an optimized tradeoff between speed, quality and price. A Gemini Pro SKU remains available as a configurable upgrade for complex analysis via Vertex. Embeddings use **`gemini-embedding-001`** at 768 dimensions (same default as the prototype), subject to retrieval evaluation.

---

## 4. Data and state model

PostgreSQL is the application system of record:
- User product entitlements,
- Conversation checkpoints,
- User preferences records,
- Persona versions,
- Report metadata and object references,
- Golden set candidates,
- Retrieval vectors
- Audit log

Cloud Storage holds production report artifacts.
External SQL-compatible data storage holds analytical facts and is readonly for the chatbot system.

A saved report is a snapshot: original question, SQL, execution timestamp, and the persona / prompt / Golden set items, as well as the pointer to the artifact in Cloud Storage. 

---

## 5. Security and governance

Authentication will be resolved via a JWT token on BFF. The user data will be forwarded to the further layers from that point on without the need for authentication.

Every analytical query — including joins, subqueries, and customer/order cuts — must have allowed-product scope injected and verified in application data-access code - this is not controlled by the LLM, but added deterministically based on the user's entitlement mapping in PostgreSQL (e.g. after JWT auth, load brands for that user such as `Calvin Klein` or `Levi's`, then rewrite SQL on `products` / `order_items` accordingly).

SQL is restricted to approved read-only operations, tables, columns, and functions, using least-privilege credentials, cost limits, timeouts, and bounded result sizes.

Raw PII stays out of model and embedding inputs by default, sanitized inputs are phone and email (as per the requirements shared on Slack).
User text, retrieved examples, tool results, errors, and traces are all sanitized. Final answers and LLM-generated artifacts are checked before release as well.

Persona/tone configuration cannot change security rules - those are deterministic application code and/or backed in system prompt that always takes precedence over the Persona prompt.

---

## 6. Reliability, scalability, deployment, and recovery

Transient provided failures get limited retries with backoff. If the limit is exceeded, the conversation state is preserved and an error is shown, with manual retry possibility. 

SQL errors and empty result sets are detected in application code on the SQL tool path. The tool returns a structured ``repair_required`` (or ``empty_result_exhausted``) payload; the agent may rewrite and retry within a per-turn empty-result budget so costs stay bounded.

In case of SSE disconnect, the analysis should continue and should be available in chat history. Long-running analyses run on a **durable worker** (Cloud Run job / worker service driven by a queue) so work outlives the HTTP/SSE connection; the chat API persists progress and the client resumes from conversation state.

The budget for recursion limit is set via configuration, as well as cost budget for the agent. 

The database should be backed up daily automatically in GCP.

---

## 7. Evaluation and observability

Evaluation should be a part of the development flow as well as a periodical gate to check system health (e.g. in a case of model changes done by the provider). Evaluation should be done via an llm-as-a-judge setup, linked to LangSmith. The test cases should cover:
- Regular analysis,
- Generated SQL queries,
- Golden set usage,
- Golden set candidate proposals,
- User preference candidates,
- Artifact creation,
- Numerical consistency,
- PII exclusion,
- Report deletion confirmation,
- Tool use (in case of extensions)

The eval set should be extended whenever a new use case is identified and implemented, and should be refined and extended during the QA phase before deploying the system to production.

**Judge model family:** Prefer a **cross-family** judge relative to the agent model (e.g. ChatGPT judging a Gemini agent; Claude is also acceptable). Different model families have different strengths, so scoring with another family makes confirmation bias — the judge rubber-stamping work that “looks like” its own style — less plausible. The prototype may default the judge to Gemini only because the engagement constrains the stack to Gemini; that is a prototype concession, not the recommended production posture.

For algorithmic parts of the system, unit tests and end to end tests will be implemented.

Live agent traces go to managed LangSmith. Trace payloads must remain PII-safe (email and phone scrubbed) before export.

Application logs (request/auth failures, turn lifecycle, tool start/end, retries, unhandled errors) use Python ``logging``. Production ships them to **GCP Cloud Logging** via the Cloud Run logging integration (structured logs on stdout) or an explicit Cloud Logging handler. The prototype keeps the same logger calls but attaches a rotating **file sink** at ``output/logs/chatbot.log`` so local debugging does not depend on GCP. Prefer logging identifiers (``user_id``, ``conversation_id``, tool names) rather than raw user message text.

Agent-level metrics (turn latency/error rate, tool ok/error, BigQuery outcomes including empty/exhausted, model retries, report delete confirm/cancel, auth failures) are exposed via Prometheus at ``GET /metrics`` from a dedicated metrics module. In production, scrape that endpoint into Cloud Monitoring (Managed Prometheus) or an equivalent; the metric names stay stable when the scrape target moves.

---

## 8. Extensibility

New capabilities (charts, email, extra sources) should attach as tools or services behind the same auth, budget, and PII gates. The architecture also allows for additional services to be added in case of larger features (e.g. an Email Service).

---

## 9. Trade-offs, risks, and requirement coverage

**Risk — unauthorized product leakage via model-written SQL.** The LLM may emit SQL that omits brand filters, joins through unscoped tables, or otherwise returns rows outside the caller's entitlements (e.g. a Calvin Klein user seeing Levi's revenue). Prompt instructions alone are not a control. **Remediation:** every query passes through deterministic application SQL validation before SQL — allowlisted read-only statements and tables only, then entitlement scope is **injected/rewritten** in code from the PostgreSQL mapping (not trusted from the model). Invalid or unscoped SQL is rejected; the agent may repair within budget, but execution never bypasses the guard. Least-privilege SQL credentials, bytes/row caps, and brand-auth evals further reduce residual risk.


| Trade-off | Default choice | Alternative |
| --- | --- | --- |
| Web UI hosting | Firebase App Hosting (GCP-aligned) | **Vercel** if the client already runs Next.js there — same BFF/API contract; only the frontend deploy target changes |
| Compute | **Cloud Run** (managed scale, less ops) | **Kubernetes** if custom networking/sidecars/multi-service scheduling are required — higher infra and operational complexity |
| Chat model | **`gemini-3.8-flash`** — lower cost and lower latency | Gemini **Pro** for harder analyses — higher quality at higher cost and slower responses |

**Open question:** backup **RPO/RTO** targets once the client sets acceptable data-loss and recovery-time budgets (daily Cloud SQL backups are the baseline until then).

| Assignment requirement | Design section |
| --- | --- |
| Hybrid intelligence / Golden retrieval and updates | 3.1, 3.3, 6 |
| Safety, PII masking, product-scoped analysis | 5 |
| Saved reports and confirmed deletion | 3.2, 4 |
| User-level preference learning | 6 |
| System-level learning loop | 6 |
| Resilience and graceful error handling | 3.1, 8 |
| Quality assurance / evaluation | 9 |
| Observability and debugging | 9 |
| Persona management without redeploy | 7 |
| Architecture, services, and data stores | 2, 4 |
| Technology rationale | 2 |
| Extensibility (new tools / sources) | 7 |
| Dataset: `thelook_ecommerce` four tables | 1, 3.1, 5 |
| Requirement coverage / open items | 10 |

