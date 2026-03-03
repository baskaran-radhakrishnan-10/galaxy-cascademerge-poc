"""
scripts/validate.py
═══════════════════════════════════════════════════════════════════════════════
Job 1 — Validate, Derive & Lookup

Purpose:
    This is the GATEKEEPER of the pipeline.
    Every PR close event fires this script — but only a genuine hotfix
    merge into a versioned hotfix branch (e.g. release-6.2.1.1) should
    trigger the cascade. Everything else is silently skipped.

    Step-by-step:
        1. Load cascade-config.json  →  reads the branch hierarchy rules
        2. Resolve event inputs      →  reads PR/dispatch details from env vars
        3. Validate hotfix pattern   →  ensures this is actually a hotfix branch
        4. Derive base release       →  release-6.2.1.2  →  release-6.2.1.0
        5. Lookup cascade chain      →  finds downstream branches to target
        6. Write cascade_context.json →  passes all data to Jobs 2 & 3

Outputs:
    cascade_context.json     Artifact uploaded by cascade.yml for Jobs 2 & 3.
                             Contains: hotfix_branch, base_release, targets,
                             pr_number, pr_title, pr_url, pr_author.

    GITHUB_OUTPUT            Sets should_proceed=true/false.
                             Jobs 2 & 3 check this before running — if false,
                             the entire pipeline stops here gracefully.

Environment variables (injected by cascade.yml from GitHub Actions context):
    EVENT_NAME         github.event_name
    PR_BASE_REF        github.event.pull_request.base.ref
    PR_NUMBER          github.event.pull_request.number
    PR_TITLE           github.event.pull_request.title
    PR_URL             github.event.pull_request.html_url
    PR_AUTHOR          github.event.pull_request.user.login
    ACTOR              github.actor  (used for manual dispatch)
    INPUT_HOTFIX       github.event.inputs.hotfix_branch  (manual dispatch only)
    INPUT_PR_NUMBER    github.event.inputs.original_pr_number  (manual dispatch only)
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import os
import re
import sys


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def write_output(key: str, value: str):
    """
    Write a key=value pair to the GITHUB_OUTPUT file.

    GitHub Actions uses this file to pass values between steps and jobs.
    Downstream jobs read these outputs using:
        needs.validate.outputs.<key>

    If GITHUB_OUTPUT is not set (e.g. local dev run), logs a warning
    instead of crashing so the script can still be tested locally.
    """
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"{key}={value}\n")
        print(f"      → GITHUB_OUTPUT  : {key}={value}")
    else:
        print(f"      [WARNING] GITHUB_OUTPUT env var not set.")
        print(f"                Skipping export of: {key}={value}")
        print(f"                (This is expected when running locally.)")


def stop(reason: str):
    """
    Gracefully halt the cascade pipeline.

    This is NOT a failure — it means the event that triggered the workflow
    is simply not a hotfix merge that requires a cascade. The pipeline will
    show as 'Success' in GitHub Actions but subsequent jobs will be skipped.

    Sets should_proceed=false so Jobs 2 & 3 are automatically skipped.
    """
    print(f"\n{'─' * 60}")
    print(f"  [SKIP] {reason}")
    print(f"         No cascade will be triggered for this event.")
    print(f"{'─' * 60}")
    write_output("should_proceed", "false")
    sys.exit(0)  # Exit code 0 = success (not an error, just a skip)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  JOB 1 — Validate, Derive & Lookup")
    print("  Script: scripts/validate.py")
    print("=" * 60)

    # ──────────────────────────────────────────────────────────────────────────
    # [1/4] LOAD CONFIGURATION
    #
    # cascade-config.json defines:
    #   - cascade_chains      : maps each base release branch to its
    #                           ordered list of downstream branches
    #   - hotfix_branch_pattern: regex to identify hotfix branches
    #                           (release-X.Y.Z.N where N >= 1)
    #
    # Example cascade_chains:
    #   "release-6.2.1.0" → ["release-6.2.3.0", "release-6.3.0.0", "develop"]
    #
    # This config is the SINGLE SOURCE OF TRUTH for branch hierarchy.
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[1/4] Loading cascade-config.json ...")
    print("      This file defines the branch hierarchy and hotfix pattern.")

    with open("cascade-config.json") as f:
        config = json.load(f)

    cascade_chains  = config.get("cascade_chains", {})
    hotfix_pattern  = config.get("hotfix_branch_pattern", "")

    print(f"      Hotfix pattern    : {hotfix_pattern}")
    print(f"      Defined chains    : {len(cascade_chains)} base release(s)")
    for base, chain in cascade_chains.items():
        print(f"        {base}  →  {' → '.join(chain)}")

    # ──────────────────────────────────────────────────────────────────────────
    # [2/4] RESOLVE TRIGGER INPUTS
    #
    # The pipeline supports two trigger modes:
    #
    #   A) pull_request [closed + merged]
    #      Fires automatically when a PR is merged.
    #      All PR details are read from GitHub event context env vars.
    #      hotfix_branch = the PR's BASE branch (what was merged INTO)
    #      e.g. PR: feature-6.2.1.2 → release-6.2.1.2
    #           hotfix_branch = release-6.2.1.2
    #
    #   B) workflow_dispatch
    #      Manually triggered from GitHub Actions UI or CLI.
    #      hotfix_branch and pr_number are provided as inputs.
    #      Useful as a fallback if the PR event was missed.
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[2/4] Resolving trigger inputs ...")

    event = os.environ.get("EVENT_NAME", "")
    print(f"      Trigger event     : {event}")

    if event == "workflow_dispatch":
        # ── Manual dispatch mode ──────────────────────────────────────────
        # User manually provided the hotfix branch name via GitHub Actions UI.
        # The PR number is optional (defaults to 0 if not provided).
        hotfix_branch = os.environ.get("INPUT_HOTFIX", "").strip()
        pr_number     = int(os.environ.get("INPUT_PR_NUMBER", "0") or "0")
        pr_title      = f"Manual cascade from {hotfix_branch}"
        pr_url        = ""   # No PR URL available for manual runs
        pr_author     = os.environ.get("ACTOR", "")

        print(f"      Mode              : Manual dispatch (workflow_dispatch)")
        print(f"      Triggered by      : {pr_author}")

    else:
        # ── Automatic PR merge mode ───────────────────────────────────────
        # The workflow fired because a PR was closed.
        # IMPORTANT: hotfix_branch is the BASE ref (what was merged INTO),
        # not the HEAD ref (the feature branch that was merged FROM).
        # We care about the destination because that determines the cascade chain.
        hotfix_branch = os.environ.get("PR_BASE_REF", "").strip()
        pr_number     = int(os.environ.get("PR_NUMBER", "0") or "0")
        pr_title      = os.environ.get("PR_TITLE", "")
        pr_url        = os.environ.get("PR_URL", "")
        pr_author     = os.environ.get("PR_AUTHOR", "")

        print(f"      Mode              : Automatic (PR merge event)")

    # Log all resolved values for full traceability in the Actions run log
    print(f"      Hotfix branch     : {hotfix_branch}")
    print(f"      PR number         : #{pr_number}")
    print(f"      PR title          : {pr_title}")
    print(f"      PR author         : {pr_author}")
    print(f"      PR URL            : {pr_url or '(not available)'}")

    # ──────────────────────────────────────────────────────────────────────────
    # [3/4] VALIDATE HOTFIX BRANCH PATTERN
    #
    # Not every merged PR should trigger a cascade.
    # Only PRs merged into a HOTFIX branch should cascade.
    #
    # Hotfix branch naming convention:
    #   release-X.Y.Z.N  where N >= 1
    #   Examples: release-6.2.1.1, release-6.2.1.2, release-6.3.0.5
    #
    # Base release branches end in .0 (e.g. release-6.2.1.0) → NOT hotfix
    # Regular feature PRs merge into develop or release/*.0 → NOT hotfix
    #
    # Pattern from config: release-\d+\.\d+\.\d+\.[1-9]\d*$
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[3/4] Validating hotfix branch pattern ...")
    print(f"      Branch to validate : '{hotfix_branch}'")
    print(f"      Regex pattern      : {hotfix_pattern}")

    # Guard: branch name must have been resolved
    if not hotfix_branch:
        stop("Hotfix branch name is empty — could not be resolved from event context.")

    # Guard: branch name must match the hotfix naming convention
    if hotfix_pattern and not re.search(hotfix_pattern, hotfix_branch):
        stop(
            f"'{hotfix_branch}' does NOT match hotfix pattern '{hotfix_pattern}'.\n"
            f"         This branch is not a hotfix release — cascade not needed."
        )

    print(f"      [PASS] '{hotfix_branch}' IS a valid hotfix branch ✓")

    # ──────────────────────────────────────────────────────────────────────────
    # [4/4] DERIVE BASE RELEASE & LOOKUP CASCADE CHAIN
    #
    # The cascade-config.json is keyed by BASE RELEASE branches (.0 suffix),
    # not by individual hotfix branches (.1, .2, .3 etc.).
    # This keeps the config stable — you never need to update it per hotfix.
    #
    # Derivation rule:
    #   Strip the last version segment and replace with .0
    #   release-6.2.1.2  →  release-6.2.1.0
    #   release-6.3.0.5  →  release-6.3.0.0
    #
    # Then look up the base release in cascade_chains to find the
    # ordered list of downstream branches that need forward PRs.
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[4/4] Deriving base release and looking up cascade chain ...")

    # Replace the trailing .N (hotfix number) with .0 (base release)
    base_release = re.sub(r'\.\d+$', '.0', hotfix_branch)
    print(f"      Derivation         : {hotfix_branch}  →  {base_release}")
    print(f"      Looking up         : cascade_chains['{base_release}']")

    targets = cascade_chains.get(base_release, [])

    # Guard: the derived base release must have a cascade chain in config
    if not targets:
        stop(
            f"No cascade chain found for '{base_release}' in cascade-config.json.\n"
            f"         Add an entry for '{base_release}' if this branch should cascade."
        )

    print(f"      Cascade chain      : {' → '.join(targets)}")
    print(f"      Total forward PRs  : {len(targets)} PR(s) will be created in Job 2")

    # ──────────────────────────────────────────────────────────────────────────
    # WRITE cascade_context.json
    #
    # This file is the data contract between Job 1, Job 2, and Job 3.
    # It is uploaded as a GitHub Artifact by cascade.yml so each job
    # running on a fresh runner can download and read it.
    #
    # Fields:
    #   hotfix_branch  The branch the fix was merged into (e.g. release-6.2.1.2)
    #   base_release   Derived base (e.g. release-6.2.1.0) used for config lookup
    #   targets        Ordered list of branches that need forward PRs
    #   pr_number      Original PR number (for traceability in forward PR bodies)
    #   pr_title       Original PR title
    #   pr_url         Link back to original PR
    #   pr_author      Who merged the original PR
    # ──────────────────────────────────────────────────────────────────────────
    context = {
        "hotfix_branch": hotfix_branch,   # e.g. "release-6.2.1.2"
        "base_release":  base_release,    # e.g. "release-6.2.1.0"
        "targets":       targets,         # e.g. ["release-6.2.3.0", "develop"]
        "pr_number":     pr_number,       # e.g. 42
        "pr_title":      pr_title,        # e.g. "fix: critical payment bug"
        "pr_url":        pr_url,          # e.g. "https://github.com/org/repo/pull/42"
        "pr_author":     pr_author,       # e.g. "baskaran-radhakrishnan-10"
    }

    with open("cascade_context.json", "w") as f:
        json.dump(context, f, indent=2)

    print(f"\n      cascade_context.json written — will be uploaded as GitHub Artifact.")
    print(f"      Full contents:")
    print(f"{json.dumps(context, indent=8)}")

    # ──────────────────────────────────────────────────────────────────────────
    # SIGNAL DOWNSTREAM JOBS TO PROCEED
    #
    # Writing should_proceed=true to GITHUB_OUTPUT unlocks Jobs 2 & 3.
    # Both jobs have:   if: needs.validate.outputs.should_proceed == 'true'
    # ──────────────────────────────────────────────────────────────────────────
    print("\n      Signalling downstream jobs to proceed ...")
    write_output("should_proceed", "true")

    print("\n✅ Job 1 complete — cascade is valid. Handing off to Job 2.")
    print("=" * 60)


if __name__ == "__main__":
    main()
