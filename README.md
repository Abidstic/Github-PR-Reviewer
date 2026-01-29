# GitHub Reviewer AI 🤖

AI-powered code reviewer assignment system using frequency-weighted skill matching.

## Features

- ✅ Automatic PR analysis on creation
- ✅ AI-powered reviewer suggestions based on expertise
- ✅ Frequency-weighted skill matching
- ✅ GitHub App integration with webhook support
- ✅ SQLite-backed profile storage

## Project Structure

- `src/data_fetcher/` - Fetch PR and review data from GitHub
- `src/profile_generator/` - Generate reviewer profiles using AI
- `src/reviewer_assigner/` - Match PRs to best reviewers
- `src/github_app/` - GitHub App webhook server
- `data/` - Data storage (profiles, cache)
- `config/` - Configuration files and prompts

## Setup

1. **Clone repository**

    ```bash
    git clone <your-repo-url>
    cd github-pr-reviewer
    ```

2. **Install dependencies**

    ```bash
    pip install -r requirements.txt
    ```

3. **Configure environment**

    ```bash
    cp .env.example .env
    # Edit .env and fill in your credentials:
    # - GITHUB_TOKEN (GitHub personal access token)
    # - OPENAI_API_KEY (OpenRouter API key)
    # - GITHUB_WEBHOOK_SECRET (for webhook verification)
    ```

4. **Initial setup** (one-time per repository)

    ```bash
    # Fetch PR data, generate profiles, create vector store
    python app.py --mode setup --repo owner/repo

    # Example:
    python app.py --mode setup --repo moment/moment --max-prs 100
    ```

## Usage

### 🚀 Run Webhook Server (Production)

Start the webhook server to automatically process new PRs:

```bash
python app.py --mode webhook --port 5000
```

The server will listen for GitHub webhook events and automatically suggest reviewers for new PRs.

**Endpoints:**

- `POST /webhook` - GitHub webhook endpoint
- `GET /health` - Health check
- `GET /` - API info

### 🔄 Update Reviewer Profiles

Refresh profiles with latest PR data:

```bash
python app.py --mode update-profiles --repo owner/repo
```

### 🧪 Test the System

Run the complete workflow test:

```bash
python tests/test_complete_workflow.py
```

## Research

This tool is part of a research project on AI-based code reviewer assignment.

**Goal**: Prove that frequency-weighted skill matching produces better reviewer suggestions than manual assignment.

## License

MIT

python app.py --mode setup --repo express/express --max-prs 10

# 1. Remove the broken venv

deactivate # If you're in venv
rm -rf .venv

# 2. Create fresh venv

python3 -m venv .venv
source .venv/bin/activate

# 3. Upgrade pip

pip install --upgrade pip

# 4. Install in ORDER (this is important!)

pip install python-dotenv pyyaml PyGithub requests

# 5. Install LangChain ecosystem TOGETHER

pip install langchain==0.3.0 langchain-openai==0.2.0 langchain-community==0.3.0 langchain-core==0.3.0 openai==1.56.1

# 6. Install ML packages

pip install torch==2.2.0 --index-url https://download.pytorch.org/whl/cpu
pip install sentence-transformers==2.5.1 faiss-cpu==1.7.4

# 7. Install rest

pip install pandas==2.1.4 numpy==1.24.3 flask==3.0.0 gunicorn==21.2.0 pydantic==2.7.4
