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
- users are entitled to a defined set of products, stored as a user-to-product mapping in PostgreSQL
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
    participant API as Chat backend
    participant PG as PostgreSQL
    participant Emb as Vertex embeddings
    participant LLM as Vertex Gemini
    participant BQ as BigQuery

    User->>UI: Question
    UI->>API: Authenticated request
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
    API-->>UI: SSE progress + validated content
    API->>PG: Persist turn state and sanitized evidence
```

### 2.2 Confirmed report deletion

TODO: Do we want a dedicated UI outside of the chatbot?

Report removal is a destructive action, and as such should be an application-controlled workflow. When the user requests to delete a report, the chatbot can resolve the report in question and should show an approval UI (frontend component shown via a tool call), which, upon approval, should call an HTTP endpoint to delete the report. The agent should never have access to delete the report directly.

TODO: Fix the diagram to the description

```mermaid
sequenceDiagram
    actor User
    participant UI as Web UI
    participant API as Chat backend
    participant PG as PostgreSQL
    participant GCS as Cloud Storage

    User->>UI: Delete request (natural language or UI)
    UI->>API: Authenticated delete intent
    API->>PG: Resolve owned report IDs
    API-->>UI: Preview titles, count, consequences
    API->>PG: Persist pending op + token + expiry
    User->>UI: Explicit confirm
    UI->>API: Confirmation token
    API->>PG: Recheck ownership and pending state
    API->>PG: Delete only the frozen selection
    API->>GCS: Remove or tombstone artifacts
    API->>PG: Audit event
    API-->>UI: Deletion result
```

### 2.3 Golden set and learning

TODO: Add the separate UI

Part of the analysis loop is deciding whether a given analysis topic is a good candidate for the Golden Set - so a report generated based on a question, together with it's SQL Query. When a candidate has been identified, it is saved in the PostgreSQL database and a dedicated UI is being shown to the user, similarly to report deletion confirmation. Once a candidate has been confirmed, it is being added to the Pub/Sub and subsequently ran through embedding and saved in pgVector, and the candidate status is changed to accepted. Ingestion implementation must provide idempotency and retries.

The candidate record includes the Question/SQL/Report trio as well as metadata such as used model, user, provenance. 

Once an entry has been retired (through a dedicated UI), it is dropped out of retrieval immediately, but history is kept.

At query time the Chatbot Service embeds a contextualized question with the same model and dimensions as the index, filters to approved and in-scope entries, retrieves a small budgeted set, and treats those examples as methodology — then generates fresh SQL under the same security controls. User preferences are stored with provenance and used as part of the context as well.

TODO: Fix the diagram to the description

```mermaid
sequenceDiagram
    actor Analyst
    participant Admin as Admin UI
    participant API as Chat backend
    participant PG as PostgreSQL
    participant Bus as Pub/Sub
    participant Ingest as Ingestion service
    participant Emb as Vertex embeddings

    Analyst->>Admin: Review / edit candidate
    Admin->>API: Approve version
    API->>PG: Persist approved immutable version
    API->>PG: Write outbox event
    API->>Bus: Publish entry ID + version
    Bus->>Ingest: Ingestion event
    Ingest->>PG: Reload and verify that version
    Ingest->>Emb: Embed PII-safe chunks
    Ingest->>PG: Upsert vectors and mark indexed
    Ingest-->>Bus: Ack
```

### 2.4 Persona management

Authorized non-developers edit presentation and tone in the admin UI. PostgreSQL stores versions, author, timestamps, and which configuration is active for audit purposes. There is only one global persona active at any given time. The persona prompt is deprioritized so that it can only affect the tone, and not any other parts of the system prompt.

Each analysis records the persona version it used. 

---

## 3. Architecture and technology rationale

TODO: BFF

The general setup will be a Next.js web UI, connected to a BFF API, responsible for user authentication, request logging and routing to the proper service. This ensures proper separation of concerns as well as extensibility for the future.  BFF is the only service reachable from outside of the network.

Behind this BFF there will be two main services - the Chatbot service, which will hold majority of the logic for the user flows - orchestrating a bounded LangGraph analysis loop for the chatbot, Golden Set examples retrieval, persona injection, persisting user reports etc. The other service would be the Indexing Service, responsible for initial indexing of the Golden Set, as well as ongoing ingestion of new approved candidates. All backend services will be running Python/Starlette on Cloud Run.

Google Pub/Sub is used for queuing of the Golden Set items for indexing, Indexing Service drains this queue.

TODO: Decide between Vercel and Google Frontend offering

User report snapshot files will be persisted in Cloud Storage.

For agent observability, a managed LangSmith service is used. TODO: Application logs

Persistent storage is delivered via CloudSQL PostgreSQL database with pgvector for Golden Set embeddings.  

Cloud Run is the baseline compute choice because both the chat API and Golden ingestion are independently scalable HTTP or event-driven services with all durable state outside the process.

Kubernetes is a future option only if concrete requirements (custom networking, sidecars, multi-service scheduling) justify the operational overhead.  This option should be kept in mind during implementation.

Vertex API is chosen as a Gemini production offering, due to alignment with other GCP services we are using, IAM integration and service accounts, ops alignment and enterprise data handling.

```mermaid
flowchart TB
    subgraph Clients["1. Presentation"]
        UI["Web UI — Firebase App Hosting / Vercel
        Chat, Golden review, persona editing"]
        CLI["CLI — prototype"]
    end

    subgraph Application["2. Application — Cloud Run"]
        Backend["Chatbot backend
        Starlette + REST / SSE
        LangChain / LangGraph
        Bounded analysis loop"]
        Ingestion["Golden ingestion service
        Validate, chunk, embed, index"]
    end

    subgraph Messaging["3. Messaging"]
        PubSub["Google Cloud Pub/Sub"]
    end

    subgraph AI["4. Models — Vertex AI"]
        Chat["Gemini chatbot
        Default: Flash
        Complex analysis: Pro"]
        Embedding["Gemini Embedding
        gemini-embedding-001"]
    end

    subgraph Data["5. Data sources and persistence"]
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

    subgraph Operations["6. Observability and evaluation"]
        LangSmith["LangSmith
        Sanitized traces, debugging, evaluations"]
    end

    UI -->|"Authenticated requests"| Backend
    CLI -->|"Chat requests"| Backend
    Backend -->|"PII-checked responses / SSE"| UI
    Backend -->|"PII-checked responses"| CLI

    Backend -->|"Approved entry ID / version"| PubSub
    PubSub -->|"Ingestion event"| Ingestion

    Backend -->|"PII-safe prompts
    Bounded retries"| Chat
    Backend -->|"PII-safe query text"| Embedding
    Ingestion -->|"PII-safe Golden text"| Embedding

    Backend <-->|"Validated SQL / results
    Enforced product scope
    Bounded SQL repair"| BigQuery

    Backend <-->|"Persist state
    Retrieve authorized Golden examples
    Load entitlements"| Postgres

    Golden -->|"Initial ingestion"| Ingestion
    Ingestion -->|"Store approved entries and vectors"| Postgres
    Backend <-->|"Save / retrieve artifacts"| Storage

    Backend -->|"PII-safe traces"| LangSmith
    Ingestion -->|"PII-safe ingestion traces"| LangSmith
```

**Model strategy:** Flash is the default chat model as an optimized tradeoff between speed, quality and price. Pro is available as a choice for complex analysis. Both models are available as hosted Vertex APIs and exact model IDs are configurable via environment variables. Embeddings use `gemini-embedding-001` as default model (configurable via environment as well) at 768 dimensions, subject to retrieval evaluation.

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
BigQuery holds analytical facts and is readonly for the chatbot system. TODO: Ask if this is prod req or I'm supposed to propose something here

A saved report is a snapshot: original question, SQL, execution timestamp, and the persona / prompt / Golden set items, as well as the pointer to the artifact in Cloud Storage. 

---

## 5. Security and governance

Authentication will be resolved via a JWT token on BFF. The user data will be forwarded to the further layers from that point on without the need for authentication.

Every analytical query — including joins, subqueries, and customer/order cuts — must have allowed-product scope injected and verified in application data-access code - this is not controlled by the LLM, but added deterministically based on user authorization mapping in the PostgreSQL database.

SQL is restricted to approved read-only operations, tables, columns, and functions, using least-privilege credentials, cost limits, timeouts, and bounded result sizes.

Raw PII stays out of model and embedding inputs by default, sanitized inputs are phone and email (as per the requirements shared on Slack).
User text, retrieved examples, tool results, errors, and traces are all sanitized. Final answers and LLM-generated artifacts are checked before release as well.

Persona/tone configuration cannot change security rules - those are deterministic application code and/or backed in system prompt that always takes precedence over the Persona prompt.

---

## 6. Reliability, scalability, deployment, and recovery

Transient provided failures get limited retries with backoff. If the limit is exceeded, the conversation state is preserved and an error is shown, with manual retry possibility. 

SQL errors can trigger a bounded SQL repair by the agent.

TODO:

This section should cover SSE reconnect behavior, whether analysis continues after disconnect, **proposed** durable execution for work that must outlive HTTP, Pub/Sub redelivery and poison events, concurrency and cost budgets, Cloud Run min/max instances, and backup/rollback procedures. Do not invent business-approved SLA, RTO, or RPO numbers.

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

---

## 8. Extensibility

New capabilities (charts, email, extra sources) should attach as tools or services behind the same auth, budget, and PII gates. The architecture also allows for additional services to be added in case of larger features (e.g. an Email Service).

---

## 9. Trade-offs, risks, open decisions, and requirement coverage

TODO:

The main trade-offs to expand here are managed Cloud Run vs Kubernetes, Flash-default vs always-Pro quality/cost, pgvector-in-Postgres vs a dedicated vector store, and snapshot reports vs later templates. The main risks are unauthorized product leakage through model-written SQL, dual-write loss between approval and indexing, analytically wrong metric grain, and PII in traces or streamed tokens.

**Open decisions:** web hosting provider; exact Gemini model IDs; real entitlement mapping; soft vs permanent deletion and artifact GC; small-cohort suppression policy; whether long analyses use a durable worker; backup RPO/RTO once the client sets them.

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



TODO: Compaction
