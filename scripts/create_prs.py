"""
scripts/create_prs.py
═══════════════════════════════════════════════════════════════════════════════
Job 2 — Create Forward PRs via GitHub API

Purpose:
    This is the CORE ACTION of the pipeline.
    Reads the resolved cascade context from Job 1 and uses the GitHub
    REST API to create one forward PR per cascade target branch.

    Each PR:
      - Has a standardised title:  "chore: cascade <hotfix> → <target> [from #N]"
      - Has a rich body with original PR details for full traceability
      - Is assigned to the target branch for lead review (not auto-merged)
      - References the original hotfix PR so nothing is ever lost

    Results (created + skipped) are written to cascade_results.json
    and uploaded as an artifact for Job 3 to include in the email.

Inputs:
    cascade_context.json     Downloaded artifact from Job 1.
                             Contains: hotfix_branch, targets, pr_number,
                             pr_title, pr_url, pr_author.

Outputs:
    cascade_results.json     Artifact uploaded for Job 3.
                             Contains: created_prs[], skipped_prs[].

Environment variables (injected by cascade.yml):
    GH_PAT             Personal Access Token with 'repo' scope.
                       Required to call the GitHub REST API and create PRs.
    GITHUB_REPOSITORY  Auto-set by GitHub Actions as "owner/repo".
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import os
import sys

import requests


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def build_pr_body(pr_title: str, pr_url: str, pr_number: int,
                  pr_author: str, hotfix_branch: str, target: str) -> str:
    """
    Build the markdown body for the auto-created forward PR.

    The body includes:
      - A reference table linking back to the original hotfix PR
      - Clear instructions for the reviewer
      - A warning not to close without merging

    This ensures every forward PR is self-contained and traceable
    back to the original fix — no digging through history required.
    """
    return (
        f"## 🤖 Automated Cascade Forward PR\n\n"
        f"| Field | Value |\n"
        f"|---|---|\n"
        f"| **Original PR** | [{pr_title}]({pr_url}) (#{pr_number}) |\n"
        f"| **Merged by** | {pr_author} |\n"
        f"| **Hotfix branch** | `{hotfix_branch}` |\n"
        f"| **Forward target** | `{target}` |\n\n"
        f"---\n\n"
        f"This PR was automatically created by the **Galaxy Cascade Automation**.\n\n"
        f"Please review the changes and merge to propagate the hotfix into `{target}`.\n\n"
        f"> ⚠️ Do **not** close this PR without merging unless the fix is "
        f"explicitly not applicable to `{target}`."
    )


def parse_api_error(response: requests.Response) -> str:
    """
    Extract a human-readable error message from a failed GitHub API response.

    GitHub returns errors in two formats:
      {"message": "..."}                         → simple error
      {"errors": [{"message": "..."}], ...}      → validation error (e.g. PR exists)

    HTTP 422 with "A pull request already exists" is the most common case —
    means a forward PR for this branch pair was already created earlier.
    """
    try:
        err_data = response.json()
        # Prefer the first entry in the errors array (validation errors)
        nested = err_data.get("errors", [{}])[0].get("message", "")
        return nested or err_data.get("message", f"HTTP {response.status_code}")
    except Exception:
        return f"HTTP {response.status_code} — could not parse response body"


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  JOB 2 — Create Forward PRs via GitHub API")
    print("  Script: scripts/create_prs.py")
    print("=" * 60)

    # ──────────────────────────────────────────────────────────────────────────
    # [1/3] LOAD CASCADE CONTEXT FROM JOB 1
    #
    # cascade_context.json was written by scripts/validate.py (Job 1)
    # and uploaded as a GitHub Artifact. cascade.yml downloads it
    # before this script runs, so it is available in the working directory.
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[1/3] Loading cascade_context.json from Job 1 ...")
    print("      This file contains all resolved cascade parameters.")

    with open("cascade_context.json") as f:
        ctx = json.load(f)

    # Unpack all fields from the context for clarity
    hotfix_branch = ctx["hotfix_branch"]   # e.g. "release-6.2.1.2"
    targets       = ctx["targets"]         # e.g. ["release-6.2.3.0", "develop"]
    pr_number     = ctx["pr_number"]       # e.g. 42
    pr_title      = ctx["pr_title"]        # e.g. "fix: critical payment bug"
    pr_url        = ctx["pr_url"]          # e.g. "https://github.com/.../pull/42"
    pr_author     = ctx["pr_author"]       # e.g. "baskaran-radhakrishnan-10"

    print(f"      Hotfix branch     : {hotfix_branch}")
    print(f"      Forward targets   : {' → '.join(targets)}")
    print(f"      Original PR       : #{pr_number} — '{pr_title}'")
    print(f"      Merged by         : {pr_author}")

    # ──────────────────────────────────────────────────────────────────────────
    # [2/3] SETUP GITHUB API CLIENT
    #
    # Authentication:
    #   Uses GH_PAT (Personal Access Token) with 'repo' scope.
    #   This token is stored as a GitHub Secret and injected by cascade.yml.
    #   We NEVER log the token value — only confirm it is set.
    #
    # Endpoint:
    #   POST /repos/{owner}/{repo}/pulls
    #   Creates a new pull request in the repository.
    #
    # Accept header:
    #   "application/vnd.github.v3+json" ensures we use the stable v3 API.
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[2/3] Setting up GitHub API connection ...")

    token = os.environ.get("GH_PAT", "")
    repo  = os.environ.get("GITHUB_REPOSITORY", "")

    if not token:
        print("      [ERROR] GH_PAT secret is not set.")
        print("              Go to: Settings → Secrets → Actions → New secret")
        sys.exit(1)

    if not repo:
        print("      [ERROR] GITHUB_REPOSITORY env var is not set.")
        print("              This is normally auto-set by GitHub Actions.")
        sys.exit(1)

    api_url = f"https://api.github.com/repos/{repo}/pulls"
    headers = {
        "Authorization": f"token {token}",        # Bearer token auth
        "Accept":        "application/vnd.github.v3+json",  # Stable API version
    }

    print(f"      GH_PAT            : {'✓ set (value hidden)' if token else '✗ NOT SET'}")
    print(f"      Repository        : {repo}")
    print(f"      API endpoint      : POST {api_url}")

    # ──────────────────────────────────────────────────────────────────────────
    # [3/3] CREATE ONE FORWARD PR PER CASCADE TARGET
    #
    # For each target branch in the cascade chain:
    #   1. Build a descriptive PR body with a back-reference to the original PR
    #   2. POST to GitHub API to create the PR
    #   3. Record the result (created or skipped with reason)
    #
    # PR naming convention:
    #   "chore: cascade <hotfix_branch> → <target> [from #<pr_number>]"
    #
    # Common skip reasons (HTTP 422):
    #   "A pull request already exists for <branch>:<hotfix_branch>"
    #   → The PR was already created — no action needed, not an error.
    # ──────────────────────────────────────────────────────────────────────────
    print(f"\n[3/3] Creating {len(targets)} forward PR(s) ...")
    print(f"      Source (head) : {hotfix_branch}")
    print(f"      Targets (base): {targets}")

    created_prs = []   # PRs successfully created — will be linked in email
    skipped_prs = []   # PRs that could not be created — included in email warning

    for i, target in enumerate(targets, start=1):
        print(f"\n      {'─' * 50}")
        print(f"      [{i}/{len(targets)}] {hotfix_branch}  →  {target}")
        print(f"      {'─' * 50}")

        # Build the PR title and body
        pr_title_forward = f"chore: cascade {hotfix_branch} → {target} [from #{pr_number}]"
        pr_body          = build_pr_body(pr_title, pr_url, pr_number,
                                         pr_author, hotfix_branch, target)

        # Construct the API request payload
        payload = {
            "title": pr_title_forward,  # Shown in GitHub PR list
            "head":  hotfix_branch,     # Branch containing the hotfix commits
            "base":  target,            # Branch the PR should merge INTO
            "body":  pr_body,           # Markdown description with traceability info
        }

        print(f"      PR title          : {pr_title_forward}")
        print(f"      Calling GitHub REST API ...")

        resp = requests.post(api_url, headers=headers, json=payload)

        print(f"      Response status   : HTTP {resp.status_code}")

        if resp.status_code == 201:
            # ── PR created successfully ───────────────────────────────────
            # HTTP 201 Created = GitHub accepted and created the pull request.
            data = resp.json()
            created_prs.append({
                "target": target,           # e.g. "release-6.2.3.0"
                "url":    data["html_url"], # e.g. "https://github.com/org/repo/pull/45"
                "number": data["number"],   # e.g. 45
            })
            print(f"      [OK] PR #{data['number']} created successfully ✓")
            print(f"           URL : {data['html_url']}")

        else:
            # ── PR creation failed ────────────────────────────────────────
            # Could be: PR already exists (422), auth error (401), etc.
            # We log the reason and continue — don't stop the whole pipeline.
            err_msg = parse_api_error(resp)
            skipped_prs.append({"target": target, "reason": err_msg})
            print(f"      [WARN] Could not create PR for '{target}'")
            print(f"             Reason : {err_msg}")
            print(f"             Action : Logged as skipped — pipeline continues.")

    # ──────────────────────────────────────────────────────────────────────────
    # WRITE cascade_results.json
    #
    # This file is the handoff to Job 3 (Notify via Email).
    # Job 3 reads created_prs to build the email table with PR links,
    # and skipped_prs to include a warning section if any PRs were missed.
    # ──────────────────────────────────────────────────────────────────────────
    results = {
        "created_prs": created_prs,   # List of {target, url, number}
        "skipped_prs": skipped_prs,   # List of {target, reason}
    }

    with open("cascade_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n      cascade_results.json written — will be uploaded as GitHub Artifact.")
    print(f"      Full contents:")
    print(f"{json.dumps(results, indent=8)}")

    # Final summary
    print(f"\n{'─' * 60}")
    print(f"  SUMMARY")
    print(f"  Created : {len(created_prs)} PR(s)")
    for pr in created_prs:
        print(f"    ✅ PR #{pr['number']} → {pr['target']}  ({pr['url']})")
    if skipped_prs:
        print(f"  Skipped : {len(skipped_prs)} PR(s)")
        for pr in skipped_prs:
            print(f"    ⚠️  {pr['target']}  — {pr['reason']}")
    print(f"{'─' * 60}")

    print(f"\n✅ Job 2 complete — Handing off results to Job 3.")
    print("=" * 60)


if __name__ == "__main__":
    main()
