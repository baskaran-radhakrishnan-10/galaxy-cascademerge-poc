"""
scripts/notify.py
═══════════════════════════════════════════════════════════════════════════════
Job 3 — Notify via Email

Purpose:
    This is the NOTIFICATION stage of the pipeline.
    Reads the cascade context (Job 1) and results (Job 2), then sends
    a single HTML email to ALL relevant team leads across every target branch.

    The email includes:
      - Original hotfix PR details (title, author, link)
      - A table of forward PRs with clickable review links
      - A clear "Action Required" banner so nothing gets missed
      - A warning section if any PRs could not be auto-created

    Recipients are resolved from team-config.json based on which
    target branches were in the cascade chain. The always_notify list
    is also included on every email.

Inputs:
    cascade_context.json     Downloaded artifact from Job 1.
    cascade_results.json     Downloaded artifact from Job 2.

Outputs:
    HTML email → delivered to all target branch leads via SMTP.

Environment variables (injected by cascade.yml):
    SMTP_HOST      Mail server hostname     e.g. smtp.gmail.com
    SMTP_PORT      Mail server port         e.g. 587
    SMTP_USERNAME  SMTP login username      e.g. your@gmail.com
    SMTP_PASSWORD  SMTP app password        (stored as GitHub Secret)
    SMTP_FROM      Sender address           e.g. galaxy-bot@company.com
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import os
import sys


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def validate_smtp_config():
    """
    Verify all required SMTP environment variables are present before
    attempting to send. Fail fast with a clear message if any are missing,
    rather than getting a cryptic SMTP connection error later.
    """
    required = ["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"]
    missing  = [var for var in required if not os.environ.get(var)]

    if missing:
        print(f"\n      [ERROR] Missing required SMTP environment variable(s):")
        for var in missing:
            print(f"              - {var}  (set this as a GitHub Secret)")
        print(f"\n              Go to: Settings → Secrets → Actions → New secret")
        sys.exit(1)

    print(f"      SMTP_HOST         : {os.environ.get('SMTP_HOST')}")
    print(f"      SMTP_PORT         : {os.environ.get('SMTP_PORT', '587 (default)')}")
    print(f"      SMTP_USERNAME     : {os.environ.get('SMTP_USERNAME')}")
    print(f"      SMTP_PASSWORD     : {'✓ set (value hidden)'}")
    print(f"      SMTP_FROM         : {os.environ.get('SMTP_FROM', os.environ.get('SMTP_USERNAME'))}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  JOB 3 — Notify via Email")
    print("  Script: scripts/notify.py")
    print("=" * 60)

    # ──────────────────────────────────────────────────────────────────────────
    # [1/3] LOAD ARTIFACTS FROM JOBS 1 & 2
    #
    # cascade_context.json  (from Job 1 / scripts/validate.py)
    #   Contains the original PR details and hotfix branch info.
    #   Used to populate the email subject and "Original PR" section.
    #
    # cascade_results.json  (from Job 2 / scripts/create_prs.py)
    #   Contains two lists:
    #     created_prs  → forward PRs that were successfully opened
    #     skipped_prs  → targets where PR creation failed (with reason)
    #
    # Both files are downloaded as GitHub Artifacts by cascade.yml
    # before this script runs, so they exist in the working directory.
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[1/3] Loading artifacts from Jobs 1 & 2 ...")

    print("      Reading cascade_context.json (from Job 1) ...")
    with open("cascade_context.json") as f:
        ctx = json.load(f)

    print("      Reading cascade_results.json (from Job 2) ...")
    with open("cascade_results.json") as f:
        results = json.load(f)

    # Unpack for clarity
    hotfix_branch = ctx["hotfix_branch"]   # e.g. "release-6.2.1.2"
    pr_number     = ctx["pr_number"]       # e.g. 42
    pr_title      = ctx["pr_title"]        # e.g. "fix: critical payment bug"
    pr_url        = ctx["pr_url"]          # e.g. "https://github.com/.../pull/42"
    pr_author     = ctx["pr_author"]       # e.g. "baskaran-radhakrishnan-10"
    created_prs   = results["created_prs"] # [{target, url, number}, ...]
    skipped_prs   = results["skipped_prs"] # [{target, reason}, ...]

    print(f"\n      Hotfix branch     : {hotfix_branch}")
    print(f"      Original PR       : #{pr_number} — '{pr_title}'")
    print(f"      Merged by         : {pr_author}")
    print(f"      PRs created       : {len(created_prs)}")
    print(f"      PRs skipped       : {len(skipped_prs)}")

    # ──────────────────────────────────────────────────────────────────────────
    # [2/3] LOG FULL PR SUMMARY & VALIDATE SMTP CONFIG
    #
    # Log every PR that was created or skipped for a complete audit trail
    # in the GitHub Actions run log. This is useful for debugging if the
    # email doesn't arrive or contains unexpected content.
    #
    # Then validate SMTP credentials before attempting to connect.
    # Fail fast with a clear error if secrets are misconfigured.
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[2/3] PR summary & SMTP validation ...")

    # Guard: if nothing happened, no point sending an email
    if not created_prs and not skipped_prs:
        print("      No PRs were created or skipped — nothing to notify about.")
        print("      Skipping email send.")
        sys.exit(0)

    # Log all forward PRs that were successfully created
    if created_prs:
        print(f"\n      Forward PRs created ({len(created_prs)}):")
        for pr in created_prs:
            print(f"        ✅ PR #{pr['number']}  :  {hotfix_branch}  →  {pr['target']}")
            print(f"                   URL : {pr['url']}")

    # Log any targets that were skipped (e.g. PR already exists)
    if skipped_prs:
        print(f"\n      Forward PRs skipped ({len(skipped_prs)}):")
        for pr in skipped_prs:
            print(f"        ⚠️  SKIPPED  :  {hotfix_branch}  →  {pr['target']}")
            print(f"                   Reason : {pr['reason']}")
        print(f"\n      NOTE: Skipped PRs will appear in the email as a warning.")
        print(f"            Recipients should create these manually if needed.")

    # Validate SMTP secrets are in place before loading the email module
    print(f"\n      Validating SMTP configuration ...")
    validate_smtp_config()

    # ──────────────────────────────────────────────────────────────────────────
    # [3/3] SEND NOTIFICATION EMAIL
    #
    # notify_forward_prs_created() is imported from notifications/email_notifier.py.
    # It handles:
    #   - Reading team-config.json to find recipients for each target branch
    #   - Including the always_notify list (global stakeholders)
    #   - Building and sending the HTML email via SMTP STARTTLS
    #
    # Recipients are determined by the TARGET branches — the people who
    # own those branches and need to review/merge the forward PRs.
    #
    # Import is done here (not at top of file) so SMTP env vars are already
    # loaded into os.environ before email_notifier.py reads them at import time.
    # ──────────────────────────────────────────────────────────────────────────
    print(f"\n[3/3] Sending notification email ...")
    print(f"      Recipients will be resolved from team-config.json")
    print(f"      for each target branch + the always_notify list.")

    # Add the repo root to sys.path so notifications/ package can be imported
    sys.path.insert(0, os.getcwd())
    from notifications.email_notifier import notify_forward_prs_created

    notify_forward_prs_created(
        original_pr_number = pr_number,
        original_pr_title  = pr_title,
        original_pr_url    = pr_url,
        author             = pr_author,
        hotfix_branch      = hotfix_branch,
        created_prs        = created_prs,   # Shown as ✅ rows in email table
        skipped_prs        = skipped_prs,   # Shown as ⚠️ rows with reason
    )

    print(f"\n      Email dispatched successfully.")
    print(f"      All target branch leads have been notified.")
    print(f"\n✅ Job 3 complete — Pipeline finished. All done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
