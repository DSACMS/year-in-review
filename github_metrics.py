"""
Generates data metrics for Year in Review.

Stripped and modified from super-changelog utils.js
to match the Year In Review template:

  - Top 10 repos      -> total commit count per repo
  - Locations         -> self-reported contributor location
  - Heat metrics      -> commit count/frequency + committer count per repo
  - Light metrics     -> stargazers (favorites) + subscribers (true watchers)
  - Love metrics      -> forks + merged PRs (upstream contributions)

Commit and contributor data is sourced from GitHub's contributor stats
endpoint (repo.get_stats_contributors) rather than paginating every
individual commit. That endpoint returns each contributor's weekly commit
counts for the repo's entire history in one (GitHub-cached) call, which is
what lets us compute both this period's totals and new-vs-returning
contributor status without walking full commit history per repo. The
trade-off: no per-commit message/url list, and no email address (stats are
keyed by GitHub account, not raw git author).
"""

from github import Github  # type: ignore
from github.GithubRetry import GithubRetry  # type: ignore
from datetime import datetime, timezone
import json
import os
import time


class GithubMetrics:
    def __init__(self, token, filename=None, log_history_start=None, log_history_end=None):
        self.now = datetime.now(timezone.utc)
        self.log_history_start = log_history_start
        self.log_history_end = log_history_end

        self.timestamp = self.now.strftime("%Y-%m-%d")
        self.start_date = (
            datetime.strptime(log_history_start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if log_history_start
            else None
        )
        self.end_date = (
            datetime.strptime(log_history_end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if log_history_end
            else None
        )

        self.filename = filename
        self.token = token
        self.g = Github(token, per_page=100, lazy=True, retry=GithubRetry(total=0))

    def _check_rate_limit(self, buffer=200):
        try:
            core = self.g.get_rate_limit().resources.core
            if core.remaining < buffer:
                reset_time = core.reset.replace(tzinfo=timezone.utc)
                wait_seconds = (reset_time - datetime.now(timezone.utc)).total_seconds()
                if wait_seconds > 0:
                    print(
                        f"Rate limit low ({core.remaining} remaining). "
                        f"Sleeping {int(wait_seconds)}s until reset."
                    )
                    time.sleep(wait_seconds + 5)
        except Exception as e:
            print(f"Error checking rate limit: {e}")

    def _record_error(self, repo_data, message):
        """Log an error and flag this repo's data as incomplete, instead of
        letting a failed fetch look identical to a genuine zero in the
        output JSON."""
        print(f"  {message}")
        repo_data.setdefault("errors", []).append(message)

    def _in_period(self, dt):
        """Whether a tz-aware datetime falls within [start_date, end_date]."""
        if self.start_date and dt < self.start_date:
            return False
        if self.end_date and dt > self.end_date:
            return False
        return True

    def _get_repo_stats(self, repo, repo_data, max_wait=30, interval=2):
        """GitHub computes contributor stats asynchronously; a repo that
        hasn't been queried recently returns None (202) while it builds the
        cache, so we poll briefly instead of failing.

        Uses a real wall-clock deadline rather than counting sleep() calls,
        since a single get_stats_contributors() call can itself take a while
        internally (retrying on a transient error) - counting only our own
        sleeps would let the loop run well past max_wait if that happens."""
        deadline = time.monotonic() + max_wait
        self._check_rate_limit()
        while time.monotonic() < deadline:
            try:
                stats = repo.get_stats_contributors()
            except Exception as e:
                self._record_error(repo_data, f"Error getting stats for {repo.name}: {e}")
                return []
            if stats is not None:
                return stats
            time.sleep(interval)
        self._record_error(repo_data, f"Stats not ready for {repo.name} after {max_wait}s, skipping")
        return []

    # ---- Locations + Heat (committer side) -------------------------------

    def get_contributors(self, repo_data, stats):
        """New/active contributors for the period, including self-reported
        location (Locations section) and company (kept for context).
        A contributor is "new" if none of their commits (per the stats
        endpoint) predate the report period's start."""
        try:
            contributors = {}

            for contributor in stats:
                author = contributor.author  # NamedUser, Organization, or None
                if author is None:
                    continue  # commits not linked to a GitHub account

                weeks_in_period = [w for w in contributor.weeks if w.c > 0 and self._in_period(w.w)]
                if not weeks_in_period:
                    continue

                had_prior_activity = any(
                    w.c > 0 and self.start_date and w.w < self.start_date for w in contributor.weeks
                )

                contributors[author.login] = {
                    "name": author.login,
                    "location": author.location,
                    "company": author.company,
                    "commit_count": sum(w.c for w in weeks_in_period),
                    "is_new": not had_prior_activity,
                }

            repo_data["contributors"] = list(contributors.values())
            repo_data["committer_count"] = len(contributors)
            print(f"  Found {len(contributors)} committers ({sum(1 for c in contributors.values() if c['is_new'])} new)")

        except Exception as e:
            self._record_error(repo_data, f"Error getting contributors for {repo_data['name']}: {e}")
            repo_data["contributors"] = []
            repo_data["committer_count"] = 0

    # ---- Top 10 repos + Heat (commit side) --------------------------------

    def get_commit_data(self, repo_data, stats):
        """Commit count/frequency, used for Top 10 ranking and Heat."""
        try:
            weekly_buckets = {}

            for contributor in stats:
                for week in contributor.weeks:
                    if week.c <= 0 or not self._in_period(week.w):
                        continue
                    week_key = week.w.strftime("%Y-W%W")
                    weekly_buckets[week_key] = weekly_buckets.get(week_key, 0) + week.c

            repo_data["total_commit_count"] = sum(weekly_buckets.values())
            repo_data["commits_per_week"] = weekly_buckets
            print(f"  Found {repo_data['total_commit_count']} commits")

        except Exception as e:
            self._record_error(repo_data, f"Error getting commit data for {repo_data['name']}: {e}")
            repo_data["total_commit_count"] = 0
            repo_data["commits_per_week"] = {}

    # ---- Light metrics -----------------------------------------------------

    def get_light_metrics(self, repo, repo_data):
        """Watchers (true subscribers) and stargazers (favorites)."""
        try:
            repo_data["stargazers_count"] = repo.stargazers_count
            # NOTE: repo.watchers_count is a v3 API alias for stargazers.
            # subscribers_count is the real "subscribed to updates" watcher count.
            repo_data["watchers_count"] = repo.subscribers_count
        except Exception as e:
            self._record_error(repo_data, f"Error getting light metrics for {repo.name}: {e}")
            repo_data["stargazers_count"] = 0
            repo_data["watchers_count"] = 0

    # ---- Love metrics --------------------------------------------------------

    def get_love_metrics(self, repo, repo_data):
        """Forks (copied projects) + merged PRs (changes contributed upstream)."""
        try:
            repo_data["forks_count"] = repo.forks_count
        except Exception as e:
            self._record_error(repo_data, f"Error getting fork count for {repo.name}: {e}")
            repo_data["forks_count"] = 0

        # merged_count lives outside the try so a mid-loop failure (e.g. a
        # timeout on one PR's merge check) keeps whatever was already
        # tallied instead of discarding the whole count back to 0.
        merged_count = 0
        try:
            if self.start_date:
                pulls = repo.get_pulls(state="closed", sort="updated", direction="desc")
                for i, pr in enumerate(pulls):
                    if i % 500 == 0:
                        self._check_rate_limit()
                    if pr.updated_at < self.start_date:
                        break  # sorted desc by update time; nothing older can match
                    if (
                        pr.is_merged()
                        and pr.merged_at
                        and pr.merged_at >= self.start_date
                        and (not self.end_date or pr.merged_at <= self.end_date)
                    ):
                        merged_count += 1
        except Exception as e:
            self._record_error(repo_data, f"Error getting merged PRs for {repo.name} (partial count kept): {e}")
        repo_data["merged_pr_count"] = merged_count

    # ---- Orchestration -------------------------------------------------------

    def get_data(self, org_name):
        try:
            org = self.g.get_organization(org_name)
        except Exception as e:
            print(f"Error getting organization {org_name}: {e}")
            raise

        data = {
            "period": {"start": self.log_history_start, "end": self.log_history_end},
            "generated_at": self.now.isoformat(),
            "total_repo_count": 0,
            "repos": [],
        }

        repos = []
        for repo in org.get_repos(type="public"):
            self._check_rate_limit()
            if not repo.archived:  # archived repos don't count toward this year's review
                repos.append(repo)

        total_repos = 0
        for repo in repos:
            total_repos += 1
            print(f"Processing repo: {repo.name}")

            repo_data = {
                "name": repo.name,
                "url": repo.html_url,
                "description": repo.description,
                "errors": [],
            }

            stats = self._get_repo_stats(repo, repo_data)
            self.get_commit_data(repo_data, stats)
            self.get_contributors(repo_data, stats)
            self.get_light_metrics(repo, repo_data)
            self.get_love_metrics(repo, repo_data)

            # A repo with any recorded error has unreliable numbers (partial
            # or zeroed-out counts) rather than genuinely being inactive -
            # data_complete lets downstream rendering (or you) distinguish
            # "really 0" from "we couldn't fetch this."
            repo_data["data_complete"] = len(repo_data["errors"]) == 0

            data["repos"].append(repo_data)

        data["total_repo_count"] = total_repos

        # Pre-sort for the "Top 10 repos" section so downstream rendering
        # doesn't need to re-derive it.
        data["top_repos_by_commits"] = [
            r["name"]
            for r in sorted(data["repos"], key=lambda r: r["total_commit_count"], reverse=True)[:10]
        ]

        return data

    def save_data(self, data):
        if not self.filename:
            return None

        dirname = os.path.dirname(self.filename)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(self.filename, "w") as f:
            json.dump(data, f, indent=2)

        return self.filename

    def get_and_save_data(self, org_name):
        data = self.get_data(org_name)
        return self.save_data(data)
