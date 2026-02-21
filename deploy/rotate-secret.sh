#!/usr/bin/env bash
# ============================================================
# Rotate a single secret in GCP Secret Manager
#
# Creates a new version without downtime — Cloud Run picks up
# the new value on the next deployment or restart.
#
# Usage:
#   ./deploy/rotate-secret.sh SENDGRID_API_KEY
#   ./deploy/rotate-secret.sh ANTHROPIC_API_KEY
# ============================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-your-gcp-project-id}"
SECRET_NAME="${1:-}"

if [ -z "$SECRET_NAME" ]; then
  echo "Usage: $0 <SECRET_NAME>"
  echo ""
  echo "Available secrets:"
  gcloud secrets list --project="$PROJECT_ID" --format="value(name)"
  exit 1
fi

echo "Rotating secret: $SECRET_NAME"
echo "Project: $PROJECT_ID"
echo ""
read -r -s -p "Enter new value (hidden): " NEW_VALUE
echo ""

if [ -z "$NEW_VALUE" ]; then
  echo "Error: empty value provided"
  exit 1
fi

echo "$NEW_VALUE" | gcloud secrets versions add "$SECRET_NAME" \
  --data-file=- \
  --project="$PROJECT_ID"

unset NEW_VALUE

echo ""
echo "✓ New version added to $SECRET_NAME"
echo ""
echo "Redeploy Cloud Run to pick up the new value:"
echo "  ./deploy/3-deploy.sh"
echo ""
echo "Or trigger a rolling restart:"
echo "  gcloud run services update-traffic cvstatuschecker --to-latest --region=REGION"
