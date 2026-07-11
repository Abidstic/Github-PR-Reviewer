# ReviewerMatch 🤖

AI-powered code reviewer assignment system using **Frequency-Weighted Skill Matching** and **Knowledge Unit (KU)** indexing.

**📦 GitHub App (public link): https://github.com/apps/reviewermatch**

## 🚀 Install & Use (GitHub App)

### Step 1 — Install the app on your repository
1. Open **https://github.com/apps/reviewermatch**
2. Click **Install** (or **Configure** if already installed)
3. Choose the account/organization, then select **Only select repositories** and pick the repo(s) you want reviewer suggestions on
4. Confirm. The app now receives `pull_request` events for those repos.

### Step 2 — Wait for automatic indexing
Installing the app automatically triggers indexing: the system fetches the repo's full PR history, builds LLM-generated reviewer skill profiles, and creates the similarity index. No action needed — allow a few minutes for small repos (longer for repos with a large PR history). Repos added to an existing installation later are indexed automatically too, and selecting **All repositories** during install works — each repo is indexed one after another.

<details>
<summary>Operator only: manual (re-)indexing</summary>

The operator can re-index a repo at any time (e.g. after a burst of new review activity). Add `"force": true` to clear checkpoints and re-process the full history:

```bash
curl -X POST https://github-pr-reviewer-production.up.railway.app/admin/setup \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: <ADMIN_SECRET>" \
  -d '{"repo": "owner/repo-name", "force": true}'
```

The `X-Admin-Secret` header must match the `ADMIN_SECRET` env var on the server.
</details>

### Step 3 — Open a pull request
That's it. When a PR is opened (or reopened), the app analyzes it and posts a comment with the top suggested reviewers, match scores, and the reasoning behind each suggestion.

**Notes:**
- The very first PR after the service has been idle can take ~1–2 minutes (model cold start); later PRs are fast
- Draft PRs are skipped until marked ready
- Reviewer profiles are built from JavaScript-ecosystem Knowledge Units, so JS/TS repositories produce the best results
- Suggestions come from the repo's own review history — repos with little past review activity will get few/no suggestions
- **Forks are supported**: if you install the app on a fork, reviewer profiles are automatically built from the *parent* repository's review history (most recent ~300 PRs), and suggestions on the fork's PRs draw from those upstream reviewers (rendered without @-mentions so no one is notified)

## 🌟 Modern Architecture

This system moves beyond simple keyword matching. It uses LLMs to extract structural expertise from historical reviews, categorizing them into defined Knowledge Units (KUs).

### 1. The KU Indexing System (JavaScript)
We index reviewer expertise across 17 distinct Knowledge Units (KUs) specifically tailored for the JavaScript ecosystem:
- **Core Concepts**: Advanced JS, Functional Programming, Data Structures, Asynchronous Programming.
- **Ecospace**: Framework/Library Expertise (React, Node, etc.), TypeScript, Mobile Dev.
- **Architecture**: API Design, Event-Driven Architecture, Error Handling.
- **Operations**: DevOps & Deployment, Dependency Management, Performance Optimization.

Each KU is tracked with a **Frequency Weight**, meaning the system knows not just *if* a reviewer knows a skill, but *how often* they have actually critiqued it in real PRs.

### 2. Expertise Scoring Logic
The final assignment score (0.0 - 1.0) is a hybrid calculation:
- **Skill Frequency (40%)**: Match between PR requirements and reviewer's KU frequency.
- **Experience Level (20%)**: Alignment of Seniority vs. PR Complexity.
- **Review Activity (20%)**: Normalized activity score using a logarithmic curve (sqrt-based) to support newer team members.
- **Similarity Match (20%)**: Vector similarity between the current PR and previous PRs the reviewer has handled.
- **Repository Bonus (+0.5)**: A weighted bonus for "Repository Veterans" who have direct experience in the target repo.

---

## 🛠 Setup & Installation

To ensure stability and avoid library conflicts (especially with LangChain and PyTorch), install dependencies in this exact order:

### 1. Environment Preparation
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

### 2. Core & API Clients
```bash
pip install python-dotenv pyyaml PyGithub requests
```

### 3. AI & LangChain Ecosystem (Strict Versions)
```bash
pip install langchain==0.3.0 langchain-openai==0.2.0 langchain-community==0.3.0 langchain-core==0.3.0 openai==1.56.1
```

### 4. Vector Search & ML Tier
```bash
# CPU-optimized PyTorch
pip install torch==2.2.0 --index-url https://download.pytorch.org/whl/cpu
# Embeddings and Vector DB
pip install sentence-transformers==2.5.1 faiss-cpu==1.7.4
```

### 5. Application Infrastructure
```bash
pip install pandas==2.1.4 numpy==1.24.3 flask==3.0.0 gunicorn==21.2.0 pydantic==2.7.4
```

---

## 🚀 Usage

### 1. Initial Setup (Repository Indexing)
Fetch historical data and build the initial KU-based profiles:
```bash
python app.py --mode setup --repo owner/repo --max-prs 50                                                                                                                       
```

### 2. Start Webhook Server (GitHub App Mode)
Listens for `pull_request.opened` events and automatically posts suggestions:
```bash
python app.py --mode webhook
```

### 3. Update Profiles
Manually refresh expertise data after a burst of review activity:
```bash
python app.py --mode update-profiles --repo owner/repo
```

---

## ⚙️ How It Works: The Workflow

1.  **Event Detection**: The `WebhookServer` receives a `pull_request.opened` event from GitHub.
2.  **Requirements Extraction**: The `PRAnalyzer` uses an LLM to identify the technical requirements, complexity, and KU needs of the new PR.
3.  **Reviewer Discovery**: The `ReviewerMatcher` queries the **SQLite database** to find all profiles that have contributed to the specific repository.
4.  **Hybrid Scoring**:
    *   **KU Match**: Reviewers are scored based on their historical frequency in the required KUs.
    *   **Context Match**: The `SimilarityMatcher` uses **FAISS** to find the top 5 most similar historical PRs and sees who reviewed them.
    *   **Team Dynamics**: Seniority and current activity levels are factored in.
5.  **Final Assignment**: The top-ranked reviewers are suggested via a GitHub comment, including reasoning for *why* they were chosen.

---

## 📁 Detailed Project Structure

- **`src/data_fetcher/`**: The entry point for data. Contains the `GitHubClient` for API interactions and `ReviewerDataFetcher` which crawls historical PRs to build the initial training set.
- **`src/profile_generator/`**: The "Intelligence" layer.
    *   `SkillAnalyzer`: Maps raw review text to the 17 JavaScript KUs.
    *   `ReviewerProfileBuilder`: Uses LLMs to generate the personality summaries and expert bios.
    *   `DeveloperProfileBuilder`: Analyzes author patterns to understand coding style.
- **`src/reviewer_assigner/`**: The "Decision" layer.
    *   `AssignmentPipeline`: Orchestrates the entire flow from analysis to suggestion.
    *   `ReviewerMatcher`: Implements the weighted hybrid scoring algorithm.
    *   `SimilarityMatcher`: Manages the FAISS vector index for deep context matching.
- **`src/github_app/`**: The "Interface" layer. Handles Flask routing, webhook signature verification, and posting results back to GitHub.
- **`config/`**: Contains `config.yaml` for system tuning and `prompts/` which houses the strict LLM templates for KU extraction.
- **`data/`**: 
    *   `profiles/`: Permanent storage for AI-generated reviewer and developer identities.
    *   `cache/`: The SQLite DB (`reviewers.db`) used for high-speed matching and checkpointing.

---

## 📊 Research Goals
This system is designed to prove that **Frequency-Weighted KU Matching** significantly outperforms manual reviewer assignment by identifying "quiet experts" who may not be the most talkative but have high-frequency technical hits in specific Knowledge Units.

## 📖 Citation

<!-- Replace the badge below with the real one from Zenodo after the first release -->
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21306453.svg)](https://doi.org/10.5281/zenodo.21306453)

If you use ReviewerMatch in your research, please cite it (see `CITATION.cff`, or use the "Cite this repository" button on GitHub):

```
Abid, M. (2026). ReviewerMatch: AI-Powered Code Reviewer Assignment using
Frequency-Weighted Knowledge Unit Matching. Zenodo. https://doi.org/10.5281/zenodo.21306453
```

**License**: MIT
