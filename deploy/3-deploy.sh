#!/usr/bin/env bash
# ============================================================
# STEP 3: Build Docker image and deploy to Cloud Run
#
# What this does:
#   1. Builds the Docker image (no secrets baked in)
#   2. Pushes to Artifact Registry
#   3. Deploys to Cloud Run with secrets injected at runtime
#      via --set-secrets (Cloud Run fetches from Secret Manager)
#   4. Connects to Cloud SQL via the Cloud SQL Auth Proxy
#      (built into Cloud Run — no proxy to manage yourself)
#
# Run AFTER: ./deploy/2-create-secrets.sh
#
# Usage:
#   chmod +x deploy/3-deploy.sh
#   ./deploy/3-deploy.sh
# ============================================================
set -euo pipefail

# ── Configuration (edit these to match 1-setup-gcp.sh) ──────
PROJECT_ID="${GCP_PROJECT_ID:-your-gcp-project-id}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="cvstatuschecker"
SA_NAME="cvchecker-sa"
DB_INSTANCE="${DB_INSTANCE:-cvchecker-db}"
ARTIFACT_REPO="cvchecker"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${SERVICE_NAME}"
# ────────────────────────────────────────────────────────────

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
CLOUD_SQL_CONNECTION=$(gcloud sql instances describe "$DB_INSTANCE" \
  --project="$PROJECT_ID" --format="value(connectionName)" 2>/dev/null || echo "")

echo "=== CV Status Checker — Cloud Run Deployment ==="
echo "Project  : $PROJECT_ID"
echo "Region   : $REGION"
echo "Image    : $IMAGE_NAME"
echo "SQL conn : $CLOUD_SQL_CONNECTION"
echo ""

# ── 1. Authenticate Docker to Artifact Registry ──────────────
echo "[1/4] Authenticating Docker to Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# ── 2. Build and push image ──────────────────────────────────
echo "[2/4] Building Docker image..."
# Use Cloud Build so credentials never leave GCP
# Alternatively: docker build + docker push (requires local Docker)
gcloud builds submit \
  --tag="${IMAGE_NAME}:latest" \
  --project="$PROJECT_ID" \
  --quiet \
  .

echo "      Image pushed: ${IMAGE_NAME}:latest"

# ── 3. Deploy to Cloud Run ───────────────────────────────────
echo "[3/4] Deploying to Cloud Run..."

# Secrets are mounted as environment variables by Cloud Run.
# The container image contains ZERO credentials.
# Format: ENV_VAR_NAME=gcp-secret-name:version
SECRET_BINDINGS=(
  "ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest"
  "SENDGRID_API_KEY=SENDGRID_API_KEY:latest"
  "SENDGRID_FROM_EMAIL=SENDGRID_FROM_EMAIL:latest"
  "SENDGRID_FROM_NAME=SENDGRID_FROM_NAME:latest"
  "GOOGLE_DRIVE_FOLDER_ID=GOOGLE_DRIVE_FOLDER_ID:latest"
  "APP_BASE_URL=APP_BASE_URL:latest"
  "SECRET_KEY=SECRET_KEY:latest"
  "ADMIN_API_KEY=ADMIN_API_KEY:latest"
  "DATABASE_URL=DATABASE_URL:latest"
)

# Join secrets with comma for the gcloud flag
SECRETS_FLAG=$(IFS=','; echo "${SECRET_BINDINGS[*]}")

gcloud run deploy "$SERVICE_NAME" \
  --image="${IMAGE_NAME}:latest" \
  --platform=managed \
  --region="$REGION" \
  --service-account="$SA_EMAIL" \
  --set-secrets="$SECRETS_FLAG" \
  --add-cloudsql-instances="$CLOUD_SQL_CONNECTION" \
  --min-instances=0 \
  --max-instances=10 \
  --memory=512Mi \
  --cpu=1 \
  --timeout=300 \
  --concurrency=80 \
  --allow-unauthenticated \
  --project="$PROJECT_ID" \
  --quiet

# ── 4. Get the service URL ───────────────────────────────────
echo "[4/4] Fetching service URL..."
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --format="value(status.url)")

echo ""
echo "=== Deployment complete ==="
echo ""
echo "  Service URL: $SERVICE_URL"
echo "  API Docs:    ${SERVICE_URL}/docs"
echo "  Health:      ${SERVICE_URL}/health"
echo ""
echo "IMPORTANT — post-deploy steps:"
echo "  1. Update APP_BASE_URL secret to: $SERVICE_URL"
echo "     gcloud secrets versions add APP_BASE_URL --data-file=- <<< \"$SERVICE_URL\""
echo "     Then redeploy for tracking pixels to use the correct URL."
echo ""
echo "  2. Configure SendGrid Event Webhook:"
echo "     URL: ${SERVICE_URL}/api/track/sendgrid"
echo ""
echo "  3. Configure SendGrid Inbound Parse:"
echo "     URL: ${SERVICE_URL}/api/track/reply"
echo ""
echo "  4. Sync your Google Drive CVs:"
echo "     curl -X POST ${SERVICE_URL}/api/candidates/sync"
