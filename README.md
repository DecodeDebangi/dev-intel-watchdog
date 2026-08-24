# Autonomous Developer Intelligence & Security Watchdog (`dev-intel-watchdog`) 🛡️⚡

An autonomous, zero-cost intelligence pipeline that syncs with your GitHub repositories, parses package dependencies, aggregates tech security feeds, deduplicates stories using a consensus engine, classifies developer report categories with Google Gemini, stores history in a local RAG vector store, and alerts you via Meta WhatsApp Cloud API.

![Python Version](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white)
![Gemini AI](https://img.shields.io/badge/Google_Gemini-Free_Tier-4285F4?style=flat-square&logo=googlecloud&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)

---

## 🌟 Key Features

### 1. 🐙 Live GitHub Stack Profiling & Custom Stack Management
- **Automatic GitHub Sync:** Connects to the GitHub REST API to scan `package.json` and `requirements.txt` across all user repositories.
- **Dependency Analytics:** Counts project occurrences per package (e.g. `react` used across 15 repositories).
- **🧹 Clean Fluff (1-Click Noise Removal):** Automatically excludes developer utility noise (e.g. `@types/*`, ESLint, Babel, Prettier, Husky).
- **📋 Bulk Paste & Batch Selection:** Checkbox selection mode and bulk paste modal for effortlessly managing hundreds of dependencies.
- **➕ Custom Dependencies:** Add custom packages manually without requiring a GitHub repository.

### 2. 🧠 Smart Hybrid Feed Subscriptions
- **Auto-Detected Language Feeds:** Dynamically enables feeds based on active core languages:
  - 🐍 **PyPI Security Feed:** Auto-enabled *only* if `Python` is in active stack.
  - 🟢 **Node.js Release Feed:** Auto-enabled *only* if `JavaScript`/`TypeScript`/`Node` packages are present.
- **Ecosystem Relevance Filter:** Filters out vulnerability reports for languages not present in your stack (e.g. mutes Ruby/PHP/Rust CVEs if you write JS/Python).
- **📡 Manage Feed Sources UI:** Toggle individual feeds ON/OFF manually or click **`🔄 Reset to Auto-Detect`**.

### 3. 🏷️ Developer Report Categories
Auto-classifies all ingested intelligence into 4 developer-friendly tabs:
- **`🚨 Security & CVEs`** — Active security advisories, CVE vulnerabilities, and patch recommendations.
- **`📦 Package Releases`** — Major framework updates and package release notes.
- **`⚡ DevOps & Cloud`** — GitHub Actions, CI/CD pipeline changes, Docker, and infrastructure updates.
- **`💡 AI & Ecosystem`** — AI/ML tools, developer trends, and ecosystem announcements.

### 4. ⚖️ Consensus Engine & Deduplication
- Derives normalized topic signatures and deterministic SHA-256 keys.
- Merges multiple coverage sources for identical news into a single, high-confidence report.

### 5. 🔍 Local RAG Vector Store
- Stores past reports in a local SQLite vector database (`watchdog.db` / `rag_store.db`).
- Natural language RAG search endpoint (`/api/search?q=python+security`) to query historical advisories.

### 6. 📱 WhatsApp Security Alerts
- Sends instant WhatsApp patch notifications for urgent CVE vulnerabilities affecting active dependencies.

### 7. ⚡ High-Performance Lazy Loading UI
- Sticky left sidebar (`position: sticky`) with balanced section height flex ratios (`1.4 : 1.0 : 0.5`).
- `IntersectionObserver` infinite scrolling lazy loads 15 cards at a time for 60fps smooth scrolling.

---

## 🏗️ Architecture Data Flow

```
                                  ┌───────────────────────────┐
                                  │   GitHub REST API Sync    │
                                  │ (repos, package.json, txt)│
                                  └─────────────┬─────────────┘
                                                │
                                                ▼
┌───────────────────────────┐     ┌───────────────────────────┐
│ Live RSS / Security Feeds │ ──► │ Smart Feed Ingestion &    │
│ (PyPI, Node, NVD, GitHub) │     │ Ecosystem Filter          │
└───────────────────────────┘     └─────────────┬─────────────┘
                                                │
                                                ▼
                                  ┌───────────────────────────┐
                                  │ Consensus Engine &        │
                                  │ Topic Signature Dedup     │
                                  └─────────────┬─────────────┘
                                                │
                                                ▼
                                  ┌───────────────────────────┐
                                  │ Google Gemini 1.5 Flash   │
                                  │ AI Security Evaluator     │
                                  └─────────────┬─────────────┘
                                                │
                                                ▼
                                  ┌───────────────────────────┐
                                  │ Local RAG Vector Store    │
                                  │ (SQLite + Search Index)   │
                                  └──────┬─────────────┬──────┘
                                         │             │
                                         ▼             ▼
                           ┌──────────────────┐   ┌──────────────────┐
                           │ Web UI Dashboard │   │ WhatsApp Cloud   │
                           │  (http://8000)   │   │  CVE Alerts      │
                           └──────────────────┘   └──────────────────┘
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- **Python 3.9+**
- **Git**
- Free **Google Gemini API Key** (from [Google AI Studio](https://aistudio.google.com/))
- **GitHub Personal Access Token** (Read-only repository access)

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/DecodeDebangi/dev-intel-watchdog.git
cd dev-intel-watchdog

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Setup

Create a `.env` file from the provided `.env.example`:

```bash
cp .env.example .env
```

Edit `.env` and fill in your API credentials:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GITHUB_ACCESS_TOKEN=your_github_personal_access_token_here

# Optional: WhatsApp Cloud API Credentials
WHATSAPP_TOKEN=your_whatsapp_token
WHATSAPP_PHONE_ID=your_whatsapp_phone_id
MY_PHONE_NUMBER=your_phone_number
```

### 4. Running the Web UI Dashboard

```bash
python main.py ui
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser!

### 5. Running Manual Feed Ingestion

```bash
python main.py run
```

### 6. Setting Up Automated Daily Cron Ingestion

```bash
chmod +x add_cron.sh
./add_cron.sh
```

---

## 🔌 API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` | `GET` | Serves the single-page Web UI dashboard |
| `/api/stack` | `GET` | Returns active stack profile, dependencies, and core languages |
| `/api/stack/sync` | `POST` | Triggers live GitHub repository re-sync |
| `/api/stack/add` | `POST` | Adds a custom dependency |
| `/api/stack/remove` | `POST` | Excludes a dependency from active stack |
| `/api/stack/bulk-remove` | `POST` | Bulk excludes multiple dependencies |
| `/api/stack/clean-noise` | `POST` | 1-click auto-exclusion of ESLint, Prettier, `@types` dev noise |
| `/api/feed` | `GET` | Returns ingested technical reports & category badges |
| `/api/feed/sources` | `GET / POST` | Manages active feed sources & smart subscription overrides |
| `/api/feed/sources/reset`| `POST` | Resets feed preferences to auto-detected stack defaults |
| `/api/watchdog/run` | `POST` | Non-blocking background feed ingestion pipeline execution |
| `/api/search` | `GET` | Performs RAG natural language vector search over historical advisories |
| `/api/stats` | `GET` | Returns active package counts, report metrics, and urgent CVE stats |

---

## 🛠️ Technology Stack
- **Backend Framework:** FastAPI / Uvicorn
- **AI / LLM Engine:** Google Gemini 1.5 Flash (`google-genai` SDK)
- **Data Ingestion:** `feedparser`, `requests`, `pydantic`
- **Database / RAG Store:** SQLite
- **Frontend UI:** HTML5, Vanilla CSS, JavaScript (Inter font, JetBrains Mono, IntersectionObserver)

---

## 📄 License
This project is open-source software licensed under the [MIT License](LICENSE).
