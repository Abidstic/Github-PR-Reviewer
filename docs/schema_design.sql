-- ============================================================
-- TABLE 1: pr_window
-- The rolling window of latest 500 merged PRs per repo.
-- This is the RAW MATERIAL that profiles are built from.
-- Each row = one merged PR with its metadata.
-- ============================================================
CREATE TABLE IF NOT EXISTS pr_window (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name       TEXT NOT NULL,          -- 'owner/repo'
    pr_number       INTEGER NOT NULL,
    title           TEXT,
    description     TEXT,
    author_username TEXT NOT NULL,           -- who opened the PR
    author_id       INTEGER,
    created_at      TEXT,                    -- ISO timestamp
    merged_at       TEXT,                    -- ISO timestamp (only merged PRs enter)
    additions       INTEGER DEFAULT 0,
    deletions       INTEGER DEFAULT 0,
    changed_files   TEXT,                    -- JSON array of file paths
    changed_files_count INTEGER DEFAULT 0,
    labels          TEXT,                    -- JSON array of label strings
    window_position INTEGER,                -- 1=oldest, 500=newest (for ordering)
    added_to_window TEXT DEFAULT (datetime('now')),  -- when this PR entered the window

    UNIQUE(repo_name, pr_number)
);

CREATE INDEX IF NOT EXISTS idx_pr_window_repo ON pr_window(repo_name);
CREATE INDEX IF NOT EXISTS idx_pr_window_repo_pos ON pr_window(repo_name, window_position);
CREATE INDEX IF NOT EXISTS idx_pr_window_author ON pr_window(author_username);
CREATE INDEX IF NOT EXISTS idx_pr_window_merged ON pr_window(repo_name, merged_at);

-- ============================================================
-- TABLE 2: pr_reviews
-- Every review action on PRs in the window.
-- Links reviewers to PRs. Feeds into profile generation.
-- When a PR is evicted from pr_window, its reviews are also deleted.
-- ============================================================
CREATE TABLE IF NOT EXISTS pr_reviews (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_window_id        INTEGER NOT NULL,       -- FK to pr_window.id
    repo_name           TEXT NOT NULL,
    pr_number           INTEGER NOT NULL,
    reviewer_username   TEXT NOT NULL,           -- who did the review
    reviewer_id         INTEGER,
    review_state        TEXT,                    -- APPROVED / CHANGES_REQUESTED / COMMENTED / DISMISSED
    review_body         TEXT,                    -- the review comment text
    submitted_at        TEXT,                    -- ISO timestamp
    author_association  TEXT,                    -- MEMBER / CONTRIBUTOR / etc.

    FOREIGN KEY (pr_window_id) REFERENCES pr_window(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pr_reviews_reviewer ON pr_reviews(reviewer_username);
CREATE INDEX IF NOT EXISTS idx_pr_reviews_repo ON pr_reviews(repo_name);
CREATE INDEX IF NOT EXISTS idx_pr_reviews_pr ON pr_reviews(pr_window_id);

-- ============================================================
-- TABLE 3: pr_review_comments
-- Line-level code review comments on PRs in the window.
-- These are more granular than formal reviews — they tell us
-- which FILES a reviewer actually commented on.
-- ============================================================
CREATE TABLE IF NOT EXISTS pr_review_comments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_window_id        INTEGER NOT NULL,       -- FK to pr_window.id
    repo_name           TEXT NOT NULL,
    pr_number           INTEGER NOT NULL,
    reviewer_username   TEXT NOT NULL,
    reviewer_id         INTEGER,
    body                TEXT,
    file_path           TEXT,                    -- which file was commented on
    line_number         INTEGER,
    submitted_at        TEXT,
    author_association  TEXT,

    FOREIGN KEY (pr_window_id) REFERENCES pr_window(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pr_review_comments_reviewer ON pr_review_comments(reviewer_username);
CREATE INDEX IF NOT EXISTS idx_pr_review_comments_file ON pr_review_comments(file_path);

-- ============================================================
-- TABLE 4: user_profiles
-- UNIFIED profile for every person (reviewer AND/OR developer).
-- One row per person per repo. The LLM-generated skill matrix
-- lives here alongside computed stats.
-- ============================================================
CREATE TABLE IF NOT EXISTS user_profiles (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    username                TEXT NOT NULL,
    repo_name               TEXT NOT NULL,          -- profiles are per-repo

    -- Role flags (a person can be both)
    is_reviewer             INTEGER DEFAULT 0,      -- 1 if they reviewed any PR in the window
    is_developer            INTEGER DEFAULT 0,      -- 1 if they authored any PR in the window

    -- Reviewer stats (from pr_reviews + pr_review_comments)
    total_reviews           INTEGER DEFAULT 0,      -- formal reviews given
    total_review_comments   INTEGER DEFAULT 0,      -- line-level comments given
    reviews_approved        INTEGER DEFAULT 0,
    reviews_changes_requested INTEGER DEFAULT 0,
    reviews_commented       INTEGER DEFAULT 0,

    -- Developer stats (from pr_window where they are author)
    total_prs_authored      INTEGER DEFAULT 0,
    total_additions         INTEGER DEFAULT 0,
    total_deletions         INTEGER DEFAULT 0,

    -- LLM-generated profile fields
    experience_level        TEXT,                    -- Junior / Mid / Senior / Lead
    primary_skills          TEXT,                    -- JSON array
    programming_languages   TEXT,                    -- JSON array
    summary                 TEXT,                    -- LLM-generated summary
    javascript_skill_matrix TEXT,                    -- JSON: the KU skill matrix

    -- Full profile JSON blob (for backward compat with matcher)
    profile_json            TEXT,

    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT DEFAULT (datetime('now')),

    UNIQUE(username, repo_name)
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_repo ON user_profiles(repo_name);
CREATE INDEX IF NOT EXISTS idx_user_profiles_user ON user_profiles(username);
CREATE INDEX IF NOT EXISTS idx_user_profiles_reviewer ON user_profiles(repo_name, is_reviewer);
CREATE INDEX IF NOT EXISTS idx_user_profiles_developer ON user_profiles(repo_name, is_developer);

-- ============================================================
-- TABLE 5: user_skills
-- Decomposed skills for fast querying (same purpose as today's
-- reviewer_skills but for unified profiles).
-- ============================================================
CREATE TABLE IF NOT EXISTS user_skills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL,
    repo_name       TEXT NOT NULL,
    skill_name      TEXT NOT NULL,
    skill_category  TEXT,
    frequency       INTEGER DEFAULT 0,

    FOREIGN KEY (username, repo_name) REFERENCES user_profiles(username, repo_name) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_skills_skill ON user_skills(skill_name);
CREATE INDEX IF NOT EXISTS idx_user_skills_user ON user_skills(username, repo_name);

-- ============================================================
-- TABLE 6: pr_user_contributions
-- CRITICAL for the subtract-on-eviction strategy.
-- Records exactly what each PR contributed to each user's profile.
-- When PR is evicted: look up contributions, subtract from profile.
-- ============================================================
CREATE TABLE IF NOT EXISTS pr_user_contributions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_window_id    INTEGER NOT NULL,           -- FK to pr_window.id
    repo_name       TEXT NOT NULL,
    pr_number       INTEGER NOT NULL,
    username        TEXT NOT NULL,               -- which user's profile was affected
    contribution_type TEXT NOT NULL,             -- 'review' or 'author'

    -- What this PR added to the user's profile
    -- Stored as JSON so we can subtract exactly what was added
    skill_deltas    TEXT,                        -- JSON: {"React": +3, "Node.js": +2, ...}
    review_count_delta INTEGER DEFAULT 0,       -- +1 if they reviewed this PR
    review_comment_delta INTEGER DEFAULT 0,     -- number of review comments on this PR
    pr_authored_delta INTEGER DEFAULT 0,        -- +1 if they authored this PR
    additions_delta INTEGER DEFAULT 0,          -- lines added (if author)
    deletions_delta INTEGER DEFAULT 0,          -- lines deleted (if author)
    approved_delta  INTEGER DEFAULT 0,          -- +1 if they approved
    changes_requested_delta INTEGER DEFAULT 0,  -- +1 if they requested changes
    commented_delta INTEGER DEFAULT 0,          -- +1 if they commented

    FOREIGN KEY (pr_window_id) REFERENCES pr_window(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_contributions_pr ON pr_user_contributions(pr_window_id);
CREATE INDEX IF NOT EXISTS idx_contributions_user ON pr_user_contributions(username, repo_name);

-- ============================================================
-- TABLE 7: assignment_history (KEPT from current system)
-- Tracks every suggestion the bot has posted.
-- Useful for thesis evaluation.
-- ============================================================
CREATE TABLE IF NOT EXISTS assignment_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_number           INTEGER,
    repo_name           TEXT,
    pr_author           TEXT,
    suggested_reviewers TEXT,                    -- JSON array of usernames
    assigned_at         TEXT DEFAULT (datetime('now')),
    confidence_score    REAL
);

-- ============================================================
-- TABLE 8: repo_metadata
-- Per-repo settings and state tracking.
-- ============================================================
CREATE TABLE IF NOT EXISTS repo_metadata (
    repo_name           TEXT PRIMARY KEY,
    is_fork             INTEGER DEFAULT 0,
    parent_repo         TEXT,                   -- parent repo name if fork
    window_size         INTEGER DEFAULT 0,      -- current PR count in window
    max_window_size     INTEGER DEFAULT 500,
    last_setup_at       TEXT,
    last_pr_merged_at   TEXT,
    faiss_index_built   INTEGER DEFAULT 0,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);
