#!/usr/bin/env bash
# ============================================================
# STEP 1: One-time GCP infrastructure setup
#
# Run this ONCE to provision all GCP resources.
# After this, use 2-create-secrets.sh then 3-deploy.sh.
#
# Prerequisites:
#   - gcloud CLI installed and authenticated: gcloud auth login
#   - Billing enabled on the GCP project
#
# Usage:
#   chmod +x deploy/1-setup-gcp.sh
#   ./deploy/1-setup-gcp.sh
# ============================================================
set -euo pipefail

# ── Configuration (edit these) ──────────────────────────────
export PROJECT_ID="${GCP_PROJECT_ID:-your-gcp-project-id}"
export REGION="${GCP_REGION:-us-central1}"
export SERVICE_NAME="cvstatuschecker"
export SA_NAME="cvchecker-sa"                     # service account name
export DB_INSTANCE="cvchecker-db"                 # Cloud SQL instance name
export DB_NAME="cvchecker"
export DB_USER="cvchecker"
export ARTIFACT_REPO="cvchecker"                  # Artifact Registry repo name
# ────────────────────────────────────────────────────────────

echo "=== CV Status Checker — GCP Setup ==="
echo "Project : $PROJECT_ID"
echo "Region  : $REGION"
echo ""

# ── 1. Set active project ────────────────────────────────────
gcloud config set project "$PROJECT_ID"

# ── 2. Enable required APIs ──────────────────────────────────
echo "[1/7] Enabling GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  drive.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  --quiet

echo "      APIs enabled."

# ── 3. Create Artifact Registry Docker repository ────────────
echo "[2/7] Creating Artifact Registry repository..."
if ! gcloud artifacts repositories describe "$ARTIFACT_REPO" \
    --location="$REGION" --quiet 2>/dev/null; then
  gcloud artifacts repositories create "$ARTIFACT_REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --description="CV Status Checker container images"
fi
echo "      Repository: ${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}"

# ── 4. Create service account with least-privilege IAM ───────
echo "[3/7] Creating service account: $SA_NAME ..."
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if ! gcloud iam service-accounts describe "$SA_EMAIL" --quiet 2>/dev/null; then
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="CV Checker Cloud Run Service Account" \
    --description="Least-privilege SA for the CV Status Checker Cloud Run service"
fi

# Grant only the minimum required roles
declare -a ROLES=(
  "roles/secretmanager.secretAccessor"   # read secrets from Secret Manager
  "roles/cloudsql.client"                # connect to Cloud SQL
)

for role in "${ROLES[@]}"; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$role" \
    --quiet
done

echo "      Service account: $SA_EMAIL"
echo "      Roles granted: ${ROLES[*]}"

# ── 5. Create Cloud SQL PostgreSQL instance ──────────────────
echo "[4/7] Creating Cloud SQL instance: $DB_INSTANCE ..."
echo "      (This takes 3-5 minutes...)"

if ! gcloud sql instances describe "$DB_INSTANCE" --quiet 2>/dev/null; then
  gcloud sql instances create "$DB_INSTANCE" \
    --database-version=POSTGRES_15 \
    --tier=db-f1-micro \
    --region="$REGION" \
    --storage-auto-increase \
    --no-backup \
    --deletion-protection

  # Create database and user
  gcloud sql databases create "$DB_NAME" --instance="$DB_INSTANCE"

  # Generate a secure random DB password and store it immediately in Secret Manager
  DB_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)

  gcloud sql users create "$DB_USER" \
    --instance="$DB_INSTANCE" \
    --password="$DB_PASSWORD"

  # Store DB connection URL in Secret Manager right away
  CLOUD_SQL_CONNECTION=$(gcloud sql instances describe "$DB_INSTANCE" \
    --format="value(connectionName)")
  DB_URL="postgresql+psycopg2://${DB_USER}:${DB_PASSWORD}@/${DB_NAME}?host=/cloudsql/${CLOUD_SQL_CONNECTION}"

  echo "$DB_URL" | gcloud secrets create DATABASE_URL \
    --data-file=- \
    --replication-policy=automatic

  echo "      Cloud SQL instance: $DB_INSTANCE"
  echo "      Database URL stored in Secret Manager as: DATABASE_URL"
  echo ""
  echo "  !! DB password was generated randomly and stored ONLY in Secret Manager."
  echo "  !! It was never written to disk or shown here."
else
  echo "      Instance already exists, skipping creation."
fi

CLOUD_SQL_CONNECTION=$(gcloud sql instances describe "$DB_INSTANCE" \
  --format="value(connectionName)")
echo "      Connection name: $CLOUD_SQL_CONNECTION"

# ── 6. Configure Google Drive (service account key) ──────────
echo ""
echo "[5/7] Google Drive access ─────────────────────────────────────────"
echo "  Option A (Recommended — Workload Identity, no key file needed):"
echo "    This setup already uses the Cloud Run service account."
echo "    Share your Google Drive folder with: ${SA_EMAIL}"
echo "    Grant it 'Viewer' access on the folder."
echo ""
echo "  Option B (Service account key — only if you MUST):"
echo "    1. Go to IAM → Service Accounts → $SA_EMAIL → Keys → Add Key → JSON"
echo "    2. Store the JSON content in Secret Manager:"
echo "       cat your-key.json | gcloud secrets create GOOGLE_SERVICE_ACCOUNT_JSON --data-file=-"
echo "    3. IMMEDIATELY delete the downloaded key file."
echo "    4. Never commit it."
echo ""
echo "  → Recommended: Share the Drive folder with ${SA_EMAIL} (Option A)"
echo "    No key file is needed when running in Cloud Run with this service account."

# ── 7. Summary ───────────────────────────────────────────────
echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Share your Google Drive folder with: ${SA_EMAIL}"
echo "     (Viewer role on the folder — no project-level access)"
echo "  2. Run:  ./deploy/2-create-secrets.sh"
echo "  3. Run:  ./deploy/3-deploy.sh"
echo ""
echo "Cloud SQL connection name (needed in step 2):"
echo "  $CLOUD_SQL_CONNECTION"
