import smtplib
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import List

# ─────────────────────────────────────────────────────────────────────────────
# SMTP CONFIG — all values come from environment variables (GitHub Secrets).
# Never hardcode credentials here.
# ─────────────────────────────────────────────────────────────────────────────
SMTP_HOST     = os.environ["SMTP_HOST"]
SMTP_PORT     = int(os.environ.get("SMTP_PORT", 587))
SMTP_USERNAME = os.environ["SMTP_USERNAME"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
SMTP_FROM     = os.environ.get("SMTP_FROM", SMTP_USERNAME)


def load_team_config() -> dict:
    """Load team-config.json from repo root."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "team-config.json")
    with open(config_path) as f:
        return json.load(f)


def get_recipients_for_branch(branch: str) -> List[str]:
    """
    Returns a deduplicated list of all email addresses
    (lead + release_manager + developers) for a given branch.
    Always includes the always_notify list.
    """
    config     = load_team_config()
    recipients = set(config.get("always_notify", []))

    team = config["teams"].get(branch, {})
    if team.get("lead"):
        recipients.add(team["lead"])
    if team.get("release_manager"):
        recipients.add(team["release_manager"])
    for dev in team.get("developers", []):
        recipients.add(dev)

    return list(recipients)


def send_email(subject: str, html_body: str, recipients: List[str]):
    """Core send function — uses STARTTLS over the configured SMTP port."""
    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_FROM
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, recipients, msg.as_string())

    print(f"[EMAIL SENT] To: {recipients} | Subject: {subject}")


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL TEMPLATE 1 — Hotfix PR Raised
# Triggered when a developer opens a hotfix Pull Request.
# ─────────────────────────────────────────────────────────────────────────────
def notify_hotfix_raised(
    pr_number: int,
    pr_title: str,
    pr_url: str,
    author: str,
    source_branch: str,
    target_branch: str,
    cascade_chain: List[str]
):
    recipients = get_recipients_for_branch(target_branch)
    subject    = (
        f"[Galaxy OB] \U0001f514 Hotfix PR Raised \u2014 "
        f"{source_branch} \u2192 {target_branch} (#{pr_number})"
    )

    cascade_rows = "".join(
        f"<tr>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;"
        f"font-family:monospace;'>{branch}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;"
        f"color:#e67e22;'>\u23f3 Pending</td>"
        f"</tr>"
        for branch in cascade_chain
    )

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:620px;margin:auto;
                border:1px solid #ddd;border-radius:6px;overflow:hidden;">

      <!-- Header -->
      <div style="background:#1a3c5e;padding:18px 24px;">
        <h2 style="color:#fff;margin:0;">Galaxy Open Banking</h2>
        <p style="color:#aac4e0;margin:4px 0 0;">Hotfix Notification</p>
      </div>

      <!-- Body -->
      <div style="padding:24px;">
        <p style="font-size:15px;">
          A hotfix Pull Request has been raised and requires your attention.
        </p>

        <table style="width:100%;border-collapse:collapse;margin:16px 0;
                      background:#f9f9f9;border-radius:4px;">
          <tr>
            <td style="padding:8px 12px;font-weight:bold;width:40%;">PR Number</td>
            <td style="padding:8px 12px;">#{pr_number}</td>
          </tr>
          <tr style="background:#f0f4f8;">
            <td style="padding:8px 12px;font-weight:bold;">Title</td>
            <td style="padding:8px 12px;">{pr_title}</td>
          </tr>
          <tr>
            <td style="padding:8px 12px;font-weight:bold;">Raised By</td>
            <td style="padding:8px 12px;">{author}</td>
          </tr>
          <tr style="background:#f0f4f8;">
            <td style="padding:8px 12px;font-weight:bold;">Source Branch</td>
            <td style="padding:8px 12px;font-family:monospace;">{source_branch}</td>
          </tr>
          <tr>
            <td style="padding:8px 12px;font-weight:bold;">Target Branch</td>
            <td style="padding:8px 12px;font-family:monospace;">{target_branch}</td>
          </tr>
        </table>

        <h3 style="color:#1a3c5e;">Cascade Merge Chain</h3>
        <p style="color:#555;font-size:13px;">
          Once this PR is merged, the fix will automatically propagate to:
        </p>
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="background:#1a3c5e;color:#fff;">
              <th style="padding:8px 12px;text-align:left;">Branch</th>
              <th style="padding:8px 12px;text-align:left;">Status</th>
            </tr>
          </thead>
          <tbody>{cascade_rows}</tbody>
        </table>

        <div style="margin-top:24px;text-align:center;">
          <a href="{pr_url}"
             style="background:#1a3c5e;color:#fff;padding:12px 28px;
                    border-radius:4px;text-decoration:none;font-size:14px;">
            Review Pull Request
          </a>
        </div>
      </div>

      <!-- Footer -->
      <div style="background:#f0f4f8;padding:12px 24px;font-size:12px;color:#888;">
        Galaxy Open Banking \u2014 Automated Notification
        | {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} UTC
      </div>
    </div>
    """

    send_email(subject, html_body, recipients)


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL TEMPLATE 2 — Merge Conflict Detected
# Triggered when the cascade pipeline stops due to a conflict.
# ─────────────────────────────────────────────────────────────────────────────
def notify_merge_conflict(
    source_branch: str,
    conflict_branch: str,
    completed_merges: List[str],
    pending_merges: List[str],
    pr_number: int,
    workflow_url: str
):
    # Notify leads/devs of the conflict branch AND every downstream blocked branch.
    all_affected = [conflict_branch] + pending_merges
    recipients: set = set()
    for branch in all_affected:
        recipients.update(get_recipients_for_branch(branch))
    recipient_list = list(recipients)

    subject = (
        f"[Galaxy OB] \u26a0\ufe0f CONFLICT \u2014 "
        f"Cascade Blocked at {conflict_branch} (#{pr_number})"
    )

    completed_rows = "".join(
        f"<tr>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;"
        f"font-family:monospace;'>{b}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;"
        f"color:green;'>\u2705 Merged</td>"
        f"</tr>"
        for b in completed_merges
    )
    blocked_rows = "".join(
        f"<tr>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;"
        f"font-family:monospace;'>{b}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;"
        f"color:#e74c3c;'>\u274c Blocked</td>"
        f"</tr>"
        for b in [conflict_branch] + pending_merges
    )

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:620px;margin:auto;
                border:1px solid #ddd;border-radius:6px;overflow:hidden;">

      <!-- Header -->
      <div style="background:#c0392b;padding:18px 24px;">
        <h2 style="color:#fff;margin:0;">\u26a0\ufe0f Cascade Merge Conflict</h2>
        <p style="color:#f5b7b1;margin:4px 0 0;">Immediate action required</p>
      </div>

      <!-- Alert Banner -->
      <div style="background:#fdf2f2;border-left:4px solid #c0392b;
                  padding:14px 20px;margin:0;">
        <strong>The automated cascade merge has stopped.</strong><br/>
        A conflict was detected when merging
        <code>{source_branch}</code> into <code>{conflict_branch}</code>.
        Manual resolution is required.
      </div>

      <!-- Body -->
      <div style="padding:24px;">

        <h3 style="color:#1a3c5e;">Merge Status</h3>
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="background:#1a3c5e;color:#fff;">
              <th style="padding:8px 12px;text-align:left;">Branch</th>
              <th style="padding:8px 12px;text-align:left;">Status</th>
            </tr>
          </thead>
          <tbody>
            {completed_rows}
            {blocked_rows}
          </tbody>
        </table>

        <h3 style="color:#c0392b;margin-top:24px;">Steps to Resolve</h3>
        <ol style="font-size:14px;line-height:1.8;color:#333;">
          <li>Checkout branch <code>{conflict_branch}</code> locally</li>
          <li>Run: <code>git merge origin/{source_branch}</code></li>
          <li>Resolve all conflict markers manually</li>
          <li>Commit and push to <code>{conflict_branch}</code></li>
          <li>Re-trigger the cascade workflow from GitHub Actions</li>
        </ol>

        <div style="margin-top:24px;text-align:center;">
          <a href="{workflow_url}"
             style="background:#c0392b;color:#fff;padding:12px 28px;
                    border-radius:4px;text-decoration:none;font-size:14px;">
            View Failed Workflow
          </a>
        </div>
      </div>

      <!-- Footer -->
      <div style="background:#f0f4f8;padding:12px 24px;font-size:12px;color:#888;">
        Galaxy Open Banking \u2014 Automated Notification
        | {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} UTC
      </div>
    </div>
    """

    send_email(subject, html_body, recipient_list)
