# GitHub Reviewer AI 🤖

AI-powered code reviewer assignment system using frequency-weighted skill matching.

## Features

-   ✅ Automatic PR analysis on creation
-   ✅ AI-powered reviewer suggestions based on expertise
-   ✅ Frequency-weighted skill matching
-   ✅ GitHub App integration with webhook support
-   ✅ SQLite-backed profile storage

## Project Structure

-   `src/data_fetcher/` - Fetch PR and review data from GitHub
-   `src/profile_generator/` - Generate reviewer profiles using AI
-   `src/reviewer_assigner/` - Match PRs to best reviewers
-   `src/github_app/` - GitHub App webhook server
-   `data/` - Data storage (profiles, cache)
-   `config/` - Configuration files and prompts

## Setup

1. Clone repository
2. Copy `.env.example` to `.env` and fill in your credentials
3. Install dependencies: `pip install -r requirements.txt`
4. Run setup: `python main.py --setup`

## Usage

### Local Development

```bash
python main.py --mode webhook
```

### Generate Profiles

```bash
python main.py --mode generate-profiles --repo moment/moment
```

## Research

This tool is part of a research project on AI-based code reviewer assignment.

**Goal**: Prove that frequency-weighted skill matching produces better reviewer suggestions than manual assignment.

## License

MIT
