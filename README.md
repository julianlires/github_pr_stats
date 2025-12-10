# GitHub PR Statistics

Interactive tool to analyze pull request review times and reviewer performance metrics with SQLite caching.

## Features

- **Smart Caching**: Stores closed PR data to minimize API calls
- **Date Filtering**: Query stats by date range
- **Reviewer Metrics**: Average, fastest, and slowest review times per reviewer
- **Interactive Mode**: Keep the process alive for multiple queries

## Installation

1. **Clone and navigate to directory**
```bash
cd github_pr_stats
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your GitHub token, owner, and repo
```

## Usage

**Start interactive mode:**
```bash
python github_pr_stats.py
```

**Available commands:**
```bash
> get_stats()                      # All PRs
> get_stats(2024-01-01)            # From date to now
> get_stats(2024-01-01, 2024-12-31) # Date range
> help                             # Show help
> exit                             # Quit
```

## Output

- **PR Review Times**: Time to first review for each PR
- **Reviewer Statistics**: Average, fastest, slowest times + total reviews per reviewer

## Environment Variables

Create `.env` file with:
```env
GITHUB_TOKEN=your_github_personal_access_token
GITHUB_OWNER=organization_or_username
GITHUB_REPO=repository_name
```

## How It Works

1. Fetches all PRs from GitHub API
2. Uses cached reviews for closed PRs (stored in `github_pr_cache.db`)
3. Always fetches fresh reviews for open PRs
4. Displays comprehensive statistics filtered by your query
