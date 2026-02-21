#!/usr/bin/env bash
# ============================================================
# STEP 2: Populate Google Cloud Secret Manager
#
# This script prompts for each secret value interactively so
# they are NEVER stored in a file, shell history, or env vars.
#
# Secrets are stored encrypted in GCP Secret Manager and
# injected into Cloud Run at runtime — the container image
# contains ZERO credentials.
#
# Run AFTER: ./deploy/1-setup-gcp.sh
#
# Usage:
#   chmod +x deploy/2-create-secrets.sh
#   ./deploy/2-create-secrets.sh
# ============================================================
set -euo pipefail

export PROJECT_ID="${GCP_PROJECT_ID:-your-gcp-project-id}"

echo "=== CV Status Checker — Secret Manager Setup ==="
echo "Project: $PROJECT_ID"
echo ""
echo "You will be prompted for each secret value."
echo "Input is hidden (no echo). Values go directly to Secret Manager."
echo "They are NEVER written to disk or logged."
echo ""

# ── Helper functions ─────────────────────────────────────────

# Create or update a secret (reads from stdin, no echo)
upsert_secret() {
  local name="$1"
  local prompt="$2"
  local hint="${3:-}"

  echo "─── $name ──────────────────────────────────────"
  [ -n "$hint" ] && echo "    $hint"
  read -r -s -p "    Enter value: " value
  echo ""   # newline after hidden input

  if [ -z "$value" ]; then
    echo "    [skipped — empty value]"
    return
  fi

  if gcloud secrets describe "$name" --project="$PROJECT_ID" --quiet 2>/dev/null; then
    # Add a new version to existing secret
    echo "$value" | gcloud secrets versions add "$name" \
      --data-file=- \
      --project="$PROJECT_ID" \
      --quiet
    echo "    ✓ Updated existing secret: $name"
  else
    # Create new secret
    echo "$value" | gcloud secrets create "$name" \
      --data-file=- \
      --replication-policy=automatic \
      --project="$PROJECT_ID" \
      --quiet
    echo "    ✓ Created new secret: $name"
  fi

  # Clear variable from memory
  unset value
}

# ── Secrets ──────────────────────────────────────────────────

upsert_secret "ANTHROPIC_API_KEY" \
  "Anthropic API Key" \
  "Get from: https://console.anthropic.com/ → API Keys"

upsert_secret "SENDGRID_API_KEY" \
  "SendGrid API Key" \
  "Get from: https://app.sendgrid.com/settings/api_keys (Mail Send permission)"

upsert_secret "SENDGRID_FROM_EMAIL" \
  "SendGrid Verified Sender Email" \
  "The email address you verified in SendGrid (e.g. recruiter@yourcompany.com)"

upsert_secret "SENDGRID_FROM_NAME" \
  "Sender Display Name" \
  "e.g. 'Your Company Recruiting'"

upsert_secret "GOOGLE_DRIVE_FOLDER_ID" \
  "Google Drive Folder ID" \
  "From the folder URL: drive.google.com/drive/folders/<THIS_PART>"

upsert_secret "APP_BASE_URL" \
  "Public App URL" \
  "Your Cloud Run service URL (get after first deploy): https://cvstatuschecker-xxx-uc.a.run.app"

upsert_secret "SECRET_KEY" \
  "Application Secret Key" \
  "Random 32+ char string for signing tokens. Generate: openssl rand -base64 32"

upsert_secret "ADMIN_API_KEY" \
  "Admin API Key" \
  "Key to protect admin endpoints. Generate: openssl rand -base64 24"

# DATABASE_URL is usually already set by 1-setup-gcp.sh — skip if exists
if gcloud secrets describe "DATABASE_URL" --project="$PROJECT_ID" --quiet 2>/dev/null; then
  echo "─── DATABASE_URL ───────────────────────────────────"
  echo "    ✓ Already exists (created by setup script). Skipping."
else
  upsert_secret "DATABASE_URL" \
    "PostgreSQL Connection URL" \
    "Format: postgresql+psycopg2://user:pass@/dbname?host=/cloudsql/project:region:instance"
fi

echo ""
echo "=== All secrets stored in Secret Manager ==="
echo ""
echo "To list all secrets:"
echo "  gcloud secrets list --project=$PROJECT_ID"
echo ""
echo "To view versions of a secret:"
echo "  gcloud secrets versions list SECRET_NAME --project=$PROJECT_ID"
echo ""
echo "Next step: ./deploy/3-deploy.sh"
