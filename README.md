# ZADDP — Zombie API Discovery & Defence Platform

A full-stack cybersecurity dashboard for financial institutions to discover, classify, secure, and decommission "zombie" and "shadow" APIs. Built for hackathon/demo purposes with 75 synthetic banking API records and comprehensive security analysis tooling.

---

## Quick Start

```bash
docker compose up --build
```

Access the app at **http://localhost** (NGINX proxy on port 80).

### Login Options

1. **Sign in with Azure AD** — OAuth 2.0 via Microsoft Entra ID (configured for multi-tenant)
2. **Demo Login** — Quick access with `admin` / `admin`

---

## Architecture

```
                          ┌─────────────┐
                          │   NGINX     │
                          │  (Port 80)  │
                          └──────┬──────┘
                                 │
                    ┌────────────┼────────────┐
                    │                          │
              ┌─────▼──────┐           ┌──────▼──────┐
              │  Next.js   │           │   FastAPI   │
              │  (Port 3000)│           │  (Port 8000)│
              └────────────┘           └──────┬──────┘
                                              │
                                        ┌─────▼─────┐
                                        │ PostgreSQL │
                                        │ + Timescale│
                                        └───────────┘
```

### Services

| Service | Tech | Port | Role |
|---------|------|------|------|
| **nginx** | nginx:alpine | 80 | Reverse proxy — routes `/` to frontend, `/api` to backend |
| **frontend** | Next.js 14 | 3000 | React SPA with App Router, SSR, API routes |
| **backend** | Python 3.11 + FastAPI | 8000 | REST API with SQLAlchemy async ORM |
| **db** | PostgreSQL 15 + TimescaleDB | 5433 | Time-series hypertable for traffic metrics |

---

## Tech Stack

### Frontend

| Category | Libraries |
|----------|-----------|
| Framework | Next.js 14 (App Router), TypeScript, Tailwind CSS |
| State | TanStack React Query v5, Zustand |
| UI | shadcn/ui-inspired components, Framer Motion animations |
| Charts | Recharts (Pie, Bar, Area, Line) |
| Auth | NextAuth.js v4 (Azure AD OAuth + Credentials provider) |
| PDF Export | jsPDF + html2canvas |
| Icons | Lucide React |
| Notifications | react-hot-toast |
| Utilities | date-fns, clsx, tailwind-merge, class-variance-authority, zod |

### Backend

| Category | Libraries |
|----------|-----------|
| Framework | FastAPI with async support |
| ORM | SQLAlchemy 2.0 (async) with asyncpg |
| Validation | Pydantic v2 |
| HTTP Client | httpx (for scanner) |
| Server | Uvicorn |
| DB Driver | asyncpg (PostgreSQL native async driver) |

### Infrastructure

- **Docker Compose** — Multi-service orchestration
- **TimescaleDB** — Hypertable for time-series traffic metrics
- **NGINX** — Reverse proxy for unified entry point

---

## Features

### 1. Login & Authentication

- **Azure AD (Microsoft Entra ID)** — Full OAuth 2.0 flow via NextAuth.js
- **Demo Credentials Provider** — Quick-access login with `admin`/`admin`
- Session-based protection — Unauthenticated users redirected to `/login`
- Dark mode persisted via Zustand store

### 2. Command Center (Dashboard)

**Route:** `/dashboard`

Real-time overview of API security posture with:

- **6 Stat Cards** — Total APIs, Active, Deprecated, Orphaned, Shadow, Zombie (clickable to filtered inventory)
- **Risk Distribution Donut Chart** — API count by risk tier (critical/high/medium/low)
- **Status Trend Area Chart** — 30-day stacked area showing API status changes
- **Recent Discoveries Feed** — Latest 6 discovered APIs with timestamps
- **Critical Alerts Panel** — Top 5 highest-risk APIs with "Investigate" buttons
- **Decommission Progress Bars** — Workflow stage counts (detected → quarantined → approved → decommissioned → completed)
- **Environment Breakdown Bar Chart** — API distribution across environments
- **Monthly Scoreboard Preview** — Zombie count, decommissioned, rescued, cost savings
- **Top Owners Table** — Teams with most zombie/orphaned APIs

Auto-refreshes every 30 seconds.

### 3. API Inventory

**Route:** `/inventory`

Advanced data table with:

- **Server-side Pagination** — 25/50/100/250 rows per page
- **Sortable Columns** — Endpoint, environment, status, risk score, last seen
- **Faceted Filtering** — Status, environment, risk tier, data sensitivity
- **Global Search** — Debounced search across endpoint path, domain, owner, tags
- **Bulk Selection** — Multi-select with Assign Owner / Export actions
- **Row Actions Menu** — View details, Copy endpoint, Quarantine, Rescue, Decommission
- **Risk Gauge** — Animated circular gauge per API (green/yellow/orange/red)
- **Status Badges** — Color-coded by API status type

### 4. API Detail View

**Route:** `/inventory/[id]`

Five tabs with comprehensive API information:

| Tab | Content |
|-----|---------|
| **Overview** | Risk gauge, endpoint info, metadata, security summary bars |
| **Security** | Full security findings list with CVSS scores, evidence, remediation steps |
| **Traffic** | 24h request bar chart + response time line chart |
| **Dependencies** | Dependency graph placeholder |
| **Audit** | Audit trail (placeholder) |

**Action Bar:** Quarantine, Rescue, Decommission buttons (context-aware based on status)

### 5. API Scanner

**Route:** `/api-scanner`

A security reconnaissance tool with two tabs:

#### Scanner Tab
- **URL Input** — Enter any website URL to scan for API endpoints
- **How It Works** — Explanation of scanning methodology
- **Stats Cards** — Total discovered, high confidence count, last scan count

#### Scanned Inventory Tab
Shows discovered endpoints with:
- HTTP method badge (GET/POST/PUT/DELETE)
- Endpoint path
- **Severity Badge** — Critical/High/Medium/Low (from security analysis)
- **Confidence Badge** — High/Medium/Low
- **Expandable Details** — Source, timestamp, scan origin

##### Security Vulnerability Analysis
Each discovered endpoint is analyzed for **unauthorized access vectors**:

| Severity | Vulnerability Type |
|----------|-------------------|
| 🔴 Critical | Exposed Admin Interface, Sensitive Data Exposure |
| 🟠 High | IDOR, Authentication Bypass, Mass Assignment, GraphQL Introspection, File Operation Abuse |
| 🟡 Medium | Missing Rate Limiting, API Documentation Leakage, CORS Misconfiguration |
| 🔵 Low | Information Disclosure |

Each finding includes: description, attack vector explanation, and **copy-paste curl exploit example**.

**Clear Results** — Properly deletes all scan results from the in-memory store.

### 6. Zombie Graveyard

**Route:** `/zombie-graveyard`

Kanban-style workflow management:

- **4-Stage Kanban Board** — Detected → Quarantined → Approved → Decommissioned
- **Safety Catch Alert** — Traffic spike detection with rescue/investigate/dismiss
- **Shadow API Alert** — Banner for undocumented APIs
- **Card Details** — Risk gauge, endpoint, owner, days in stage, days since last traffic
- **Auto-Decommission Countdown** — Shows scheduled decommission dates
- **PR Tracking** — GitHub PR links per workflow
- **Detection Feed** — Live-updating feed with quarantine buttons

### 7. Security Center

**Route:** `/security-center`

Security posture overview:

- **5 Summary Cards** — APIs scanned, Critical findings, Open findings, Avg security score, Compliance
- **Findings by Severity Donut** — Critical/High/Medium/Low/Info distribution
- **Compliance Coverage Bar Chart** — PCI-DSS, GDPR, PSD2, SOX, ISO 27001
- **Top 10 Risk APIs** — Sorted by risk score with findings count

### 8. Reports

**Route:** `/reports`

Monthly Zombie Scoreboard with:

- **Executive Summary** — Zombies found, decommissioned, rescued, cost savings
- **Risk Score Trend** — 6-month area chart
- **Security Score Trend** — 6-month area chart
- **API Census** — Count by all status types
- **Top Business Units** — Teams with most zombie APIs
- **Date Range Selector** — Last month / Quarter / Year
- **PDF Export** — Client-side PDF generation with jsPDF + html2canvas
- **Regulatory Templates** — PCI-DSS, GDPR, Internal Audit cards

### 9. Settings

**Route:** `/settings`

7 configuration tabs:

| Tab | Features |
|-----|----------|
| **Discovery** | Auto-discovery toggle, scan frequency, discovery sources (gateway/sensor/manual/DNS), last scan status |
| **Classification** | Data sensitivity levels, auto-classification rules (path patterns, PII detection, heuristics), default settings |
| **Risk Scoring** | Adjustable weight sliders (data sensitivity, auth, encryption, exposure, age, traffic) with 100% validation |
| **Notifications** | Channel toggles (Email/Slack/PagerDuty/Webhook), event subscriptions, email settings |
| **Integrations** | Slack, Jira, PagerDuty, GitHub connection cards, custom webhooks with event filtering |
| **User Management** | User table with name, email, role badges, MFA status, active status |
| **Audit Log** | Real-time audit trail feed with color-coded actions |

---

## Backend Structure

### `backend/app/main.py`
FastAPI application entry point. Configures CORS, registers all routers, sets up lifespan for DB initialization, and provides a health check endpoint.

### `backend/app/database.py`
Async SQLAlchemy engine setup using `asyncpg`. Configures `create_async_engine`, `async_sessionmaker`, and provides `get_db()` dependency. The `init_db()` function creates all tables and sets up the TimescaleDB hypertable for traffic metrics.

### `backend/app/models.py`
SQLAlchemy ORM models:

| Model | Table | Description |
|-------|-------|-------------|
| `API` | `apis` | Core API inventory — endpoint, method, status, risk score, metadata |
| `SecurityFinding` | `security_findings` | Security vulnerabilities linked to APIs |
| `TrafficMetric` | `traffic_metrics` | Time-series request data (TimescaleDB hypertable) |
| `AuditTrail` | `audit_trail` | Immutable action log with before/after state |
| `DecommissionWorkflow` | `decommission_workflows` | Zombie lifecycle tracking |
| `User` | `users` | Platform users with RBAC |
| `APIDependency` | `api_dependencies` | Inter-API dependency graph |

### `backend/app/schemas.py`
Pydantic v2 models for request/response serialization. Includes `APIInventoryItem`, `APIDetail`, `SecurityFindingItem`, `TrafficMetricItem`, `DecommissionWorkflowItem`, `DashboardStats`, `PaginatedResponse`, `MonthlyScoreboard`, `APIResponse`, and more.

### Backend Routers

| Router | Prefix | Endpoints |
|--------|--------|-----------|
| `inventory.py` | `/api/v1/inventory` | List (paginated, filtered, sorted), detail, risk breakdown, security findings, quarantine/rescue/decommission actions |
| `dashboard.py` | `/api/v1` | Dashboard aggregations, monthly scoreboard |
| `zombies.py` | `/api/v1` | Zombie workflows, shadow API list |
| `reports.py` | `/api/v1/reports` | Report export initiation |
| `webhooks.py` | `/api/v1/webhooks` | Gateway log ingestion, sensor event ingestion |
| `scanner.py` | `/api/v1/scanner` | URL scanning, results retrieval, results clearing |

### `backend/app/seed.py`
Database seeder that creates:
- 75 synthetic banking API endpoints (active/deprecated/orphaned/shadow/zombie)
- 30 security findings (critical/high/medium/low/info)
- 2,250 traffic metrics (30 days × 75 APIs)
- 8 decommission workflows across all stages
- 20 API dependencies
- 25 audit trail entries
- 1 admin user

---

## Database Schema

```
apis
├── id (UUID PK)
├── endpoint_path (VARCHAR 500)
├── http_method (VARCHAR 10)
├── environment (VARCHAR 20) ─ production/staging/development/uat
├── status (VARCHAR 20) ─ active/deprecated/orphaned/shadow/zombie
├── risk_score (INT)
├── data_sensitivity (VARCHAR 20) ─ public/internal/confidential/restricted
├── owner_team, owner_email
├── business_domain, protocol, tls_version, framework
├── first_seen, last_seen, last_traffic_timestamp
├── deprecation_date, decommission_date
├── metadata (JSONB), tags (TEXT[])
└── relationships → security_findings, traffic_metrics, decommission_workflow, dependencies

security_findings
├── id (UUID PK)
├── api_id (FK → apis.id)
├── dimension, severity, title, description, evidence, remediation_steps
├── cvss_score, status, assigned_to, due_date, resolved_at/by

traffic_metrics  (TimescaleDB hypertable)
├── time (DateTime PK)
├── api_id (UUID PK, FK → apis.id)
├── request_count, error_4xx_count, error_5xx_count
├── avg/p95/p99_response_time_ms, unique_ips

decommission_workflows
├── id (UUID PK)
├── api_id (FK → apis.id, unique)
├── current_stage ─ detected/quarantined/approved/decommissioned/completed/rescued
├── all timestamps (detected/quarantined/approved/decommissioned/rescued)
├── grace_period_days, auto_decommission_date
├── pr_url, pr_status, safety_catch_triggered

users
├── id (UUID PK)
├── email (unique), name, avatar_url, role
├── team, department, mfa_enabled, last_login_at, is_active

api_dependencies
├── source_api_id (FK), target_api_id (FK)
├── dependency_type ─ calls/database/queue/event
├── strength ─ strong/weak/occasional

audit_trail
├── id (UUID PK)
├── timestamp, actor, action, target
├── before_state (JSONB), after_state (JSONB)
├── ip_address, user_agent, justification
```

---

## API Endpoints

### Inventory
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/inventory` | List APIs (page, page_size, status, environment, risk_tier, owner, data_sensitivity, protocol, search, sort_by, sort_order) |
| `GET` | `/api/v1/inventory/{id}` | API detail with security, traffic, workflow |
| `GET` | `/api/v1/inventory/{id}/risk` | Risk breakdown with weighted factors |
| `GET` | `/api/v1/inventory/{id}/security` | Security findings list |
| `POST` | `/api/v1/inventory/{id}/quarantine` | Move to zombie status + create workflow |
| `POST` | `/api/v1/inventory/{id}/rescue` | Restore to active status |
| `POST` | `/api/v1/inventory/{id}/decommission` | Mark as deprecated + complete workflow |

### Dashboard
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/dashboard` | Aggregated stats, risk distribution, alerts, progress |
| `GET` | `/api/v1/scoreboard` | Monthly report data with trends |

### Zombies & Shadows
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/zombies` | All decommission workflows with API data |
| `GET` | `/api/v1/shadows` | Shadow APIs sorted by risk |

### Scanner
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/scanner/scan` | Scan a URL for API endpoints + security analysis |
| `GET` | `/api/v1/scanner/results` | Get all scan results |
| `DELETE` | `/api/v1/scanner/results` | Clear all scan results |

### Other
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/health` | Health check |
| `POST` | `/api/v1/reports/{id}/export` | Initiate report export |
| `POST` | `/api/v1/webhooks/gateway` | Ingest gateway logs |
| `POST` | `/api/v1/webhooks/sensor` | Ingest sensor events |

---

## Frontend Structure

### Pages (App Router)

| Route | File | Description |
|-------|------|-------------|
| `/` | `app/page.tsx` | Redirects to `/login` |
| `/login` | `app/login/page.tsx` | Azure AD + Demo login form |
| `/dashboard` | `app/(authenticated)/dashboard/page.tsx` | Command Center with charts, stats, alerts |
| `/inventory` | `app/(authenticated)/inventory/page.tsx` | Data table with filtering, sorting, actions |
| `/inventory/[id]` | `app/(authenticated)/inventory/[id]/page.tsx` | 5-tab API detail view |
| `/api-scanner` | `app/(authenticated)/api-scanner/page.tsx` | URL scanner + scanned inventory |
| `/zombie-graveyard` | `app/(authenticated)/zombie-graveyard/page.tsx` | Kanban board + detection feed |
| `/security-center` | `app/(authenticated)/security-center/page.tsx` | Security findings analytics |
| `/reports` | `app/(authenticated)/reports/page.tsx` | Scoreboard + PDF export |
| `/settings` | `app/(authenticated)/settings/page.tsx` | 7-tab configuration panel |

### Components

| Component | Description |
|-----------|-------------|
| `layout/Sidebar.tsx` | Collapsible nav with 7 routes, user profile, sign-out |
| `layout/TopBar.tsx` | Search bar, dark mode toggle, user dropdown (settings + sign-out) |
| `ui/StatCard.tsx` | Animated card with icon, value, subtitle, click handler |
| `ui/StatusBadge.tsx` | Color-coded API status pill (active/deprecated/orphaned/shadow/zombie) |
| `ui/RiskGauge.tsx` | Animated SVG circular gauge (0-100) with color gradient |

### State Management

| Store | File | Purpose |
|-------|------|---------|
| `useUIStore` | `lib/store.ts` | Sidebar toggle, dark mode state |
| `useFilterStore` | `lib/store.ts` | Global search query, inventory filters |
| `useAuthStore` | `lib/store.ts` | Local auth state (legacy) |

### Data Fetching

```typescript
// lib/api.ts — All API calls centralized
api.getDashboard()        // GET /api/v1/dashboard
api.getInventory(params)  // GET /api/v1/inventory?...
api.getAPIDetail(id)      // GET /api/v1/inventory/{id}
api.quarantineAPI(id)     // POST /api/v1/inventory/{id}/quarantine
api.rescueAPI(id)         // POST /api/v1/inventory/{id}/rescue
api.decommissionAPI(id)   // POST /api/v1/inventory/{id}/decommission
api.scanURL(url)          // POST /api/v1/scanner/scan
api.getScanResults()      // GET /api/v1/scanner/results
api.clearScanResults()    // DELETE /api/v1/scanner/results
// ... and more
```

---

## Authentication

Two providers configured in `app/api/auth/[...nextauth]/route.ts`:

### Azure AD Provider
- **Client ID:** `fbeb816b-492d-4b28-b478-316ed613555c`
- **Tenant ID:** `bf46a35a-9b7c-4f28-9849-e03166140273`
- **Redirect URI:** `http://localhost:3000/api/auth/callback/azure-ad` (Web platform)
- **Scopes:** `openid profile email`
- Multi-tenant support enabled

### Demo Credentials Provider
- Hardcoded check: username `admin`, password `admin`
- Returns mock user with admin role

### Session Protection
- `(authenticated)/layout.tsx` checks session via `useSession()` hook
- Shows loading spinner while session loads
- Redirects to `/login` if unauthenticated
- All pages under `(authenticated)` route group are protected

---

## Demo Data

### 75 Synthetic Banking APIs

| Status | Count | Characteristics |
|--------|-------|-----------------|
| Active | 45 | Recent traffic, documented, owned |
| Deprecated | 12 | Sunset status, residual traffic |
| Orphaned | 8 | No owner, 120+ days stale |
| Shadow | 5 | No documentation, observed traffic |
| Zombie | 5 | 45+ days no traffic, still reachable |

### API Categories
Account Management, Payments, Card Services, Loans, User Management, Authentication, Notifications, Reporting, Compliance, Internal Tools, Analytics, Onboarding, Currency Exchange, Investments, Insurance, Mortgage, Support, Fraud Detection, Audit, Legacy Systems

### Data Distribution
- **Environments:** Production (60%), Staging (20%), Development (15%), UAT (5%)
- **Sensitivities:** Public (10%), Internal (40%), Confidential (35%), Restricted (15%)
- **Protocols:** HTTPS (85%), HTTP/gRPC/GraphQL (15%)
- **TLS:** 1.3 (60%), 1.2 (30%), 1.1 (7%), 1.0 (3%)

---

## Docker Compose

```yaml
services:
  db:       # timescale/timescaledb:latest-pg15 → port 5433
  backend:  # Python FastAPI → port 8000
  frontend: # Next.js 14 → port 3000
  nginx:    # nginx:alpine → port 80 (reverse proxy)
volumes:
  pgdata:   # Persistent PostgreSQL data
```

### Environment Variables

| Variable | Service | Description |
|----------|---------|-------------|
| `DATABASE_URL` | backend | Async PostgreSQL connection string |
| `NEXT_PUBLIC_API_URL` | frontend | Backend API base URL |
| `NEXTAUTH_SECRET` | frontend | NextAuth encryption secret |
| `NEXTAUTH_URL` | frontend | Base URL for NextAuth callbacks |
| `AZURE_AD_CLIENT_ID` | frontend | Azure AD app registration ID |
| `AZURE_AD_CLIENT_SECRET` | frontend | Azure AD app client secret |
| `AZURE_AD_TENANT_ID` | frontend | Azure AD tenant/directory ID |

---

## Development

```bash
# Frontend (standalone)
cd Zombiee/frontend
npm install
npm run dev            # http://localhost:3000

# Backend (standalone)
cd Zombiee/backend
pip install -r requirements.txt
python -m app.seed    # Seed database with demo data
uvicorn app.main:app --reload  # http://localhost:8000

# Database (standalone)
docker compose up db  # PostgreSQL on port 5433

# Full stack
docker compose up --build
```

### Key Commands

```bash
# Rebuild specific services
docker compose build frontend
docker compose build backend

# View logs
docker compose logs backend --tail=50
docker compose logs frontend --tail=50

# Reset database
docker compose down -v && docker compose up
```

---

## Security Scanner Details

The API Scanner (`/api-scanner`) works by:

1. **Fetching** the target URL via `httpx.AsyncClient`
2. **Pattern 1 — HTML Links:** Extracting `href` attributes containing `/api/`, `/v\d/`, `/rest/`, `/graphql`, `/swagger`, `/docs`, `/health`, `/status`
3. **Pattern 2 — Script References:** Finding hardcoded API URLs inside `<script>` tags
4. **Pattern 3 — Common Endpoints:** Matching against 25+ common API endpoint paths

Each discovered endpoint then runs through `analyze_endpoint_security()` which checks for:
- Exposed admin/internal interfaces
- Sensitive data exposure patterns
- Insecure Direct Object References (IDOR)
- Authentication bypass vectors
- Mass assignment vulnerabilities
- Missing rate limiting
- GraphQL introspection exposure
- API documentation leakage
- File operation abuse (path traversal, SSRF)
- CORS misconfiguration
- Information disclosure via health/status endpoints

## ZADDP CLI (local scanner)

The native `zaddp` CLI discovers HTTP services listening on your local machine and sends their endpoints to a running ZADDP server for classification.

### Install

```sh
# Homebrew
brew tap gatik1234err/zaddp
brew install zaddp

# APT
curl -fsSL https://gatik1234err.github.io/zaddp-apt/zaddp.gpg | sudo gpg --dearmor -o /usr/share/keyrings/zaddp.gpg
echo "deb [signed-by=/usr/share/keyrings/zaddp.gpg] https://gatik1234err.github.io/zaddp-apt stable main" | sudo tee /etc/apt/sources.list.d/zaddp.list
sudo apt update
sudo apt install zaddp
```

### Usage

```sh
# Check connectivity
zaddp doctor

# Discover and analyze local services
zaddp scan

# Use a remote server or specific target
zaddp scan --server http://localhost:8000 --target http://127.0.0.1:8080

# Add CMDB/workflow context and nginx logs for lifecycle prediction
zaddp scan --manifest zaddp-manifest.json --traffic-log /var/log/nginx/access.log

# CI gating and JSON export
zaddp scan --fail-on high --json --output report.json
```

See [`cli/README.md`](cli/README.md) for full configuration, discovery details, and packaging notes.
