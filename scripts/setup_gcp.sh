#!/bin/bash
# Run this ONCE in Google Cloud Shell (shell.cloud.google.com)
# It creates all the GCP resources needed and prints the GitHub secrets to add.
# Usage: bash scripts/setup_gcp.sh YOUR_PROJECT_ID

set -euo pipefail

PROJECT_ID="${1:?Usage: bash scripts/setup_gcp.sh YOUR_PROJECT_ID}"
REGION="us-central1"
SERVICE_ACCOUNT="real-estate-agent-sa"
SA_EMAIL="${SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com"
REPO_NAME="cloud-run-source-deploy"
QUEUE_NAME="lead-followups"

echo "==> Setting project to ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"

echo "==> Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  cloudtasks.googleapis.com \
  firestore.googleapis.com \
  calendar-json.googleapis.com \
  secretmanager.googleapis.com \
  --quiet

echo "==> Creating Artifact Registry repository..."
gcloud artifacts repositories create "${REPO_NAME}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="Real estate lead agent images" \
  --quiet 2>/dev/null || echo "  (repository already exists)"

echo "==> Creating service account..."
gcloud iam service-accounts create "${SERVICE_ACCOUNT}" \
  --display-name="Real Estate Lead Agent SA" \
  --quiet 2>/dev/null || echo "  (service account already exists)"

echo "==> Granting IAM roles..."
for ROLE in \
  roles/run.admin \
  roles/artifactregistry.writer \
  roles/datastore.user \
  roles/cloudtasks.enqueuer \
  roles/cloudtasks.viewer \
  roles/secretmanager.secretAccessor \
  roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --quiet 2>/dev/null
  echo "  Granted ${ROLE}"
done

echo "==> Creating Cloud Tasks queue..."
gcloud tasks queues create "${QUEUE_NAME}" \
  --location="${REGION}" \
  --quiet 2>/dev/null || echo "  (queue already exists)"

echo "==> Creating Firestore database (native mode)..."
gcloud firestore databases create \
  --location="${REGION}" \
  --quiet 2>/dev/null || echo "  (Firestore already exists)"

echo "==> Generating service account key..."
KEY_FILE="/tmp/${SERVICE_ACCOUNT}-key.json"
gcloud iam service-accounts keys create "${KEY_FILE}" \
  --iam-account="${SA_EMAIL}" \
  --quiet

echo ""
echo "============================================================"
echo " GCP SETUP COMPLETE — Add these secrets to GitHub:"
echo " Repo → Settings → Secrets and variables → Actions → New"
echo "============================================================"
echo ""
echo "  GCP_PROJECT_ID     = ${PROJECT_ID}"
echo ""
echo "  GCP_SA_KEY         = (copy the ENTIRE JSON below)"
echo ""
cat "${KEY_FILE}"
echo ""
echo "============================================================"
echo " Also store the service account key in Secret Manager"
echo " so Cloud Run can read Google credentials at runtime:"
echo "============================================================"
gcloud secrets create real-estate-agent-sa \
  --data-file="${KEY_FILE}" \
  --quiet 2>/dev/null || \
  gcloud secrets versions add real-estate-agent-sa \
    --data-file="${KEY_FILE}" \
    --quiet
echo ""
echo "  Secret 'real-estate-agent-sa' stored in Secret Manager ✅"
echo ""
echo "  GOOGLE_APPLICATION_CREDENTIALS is automatically mounted by"
echo "  the Cloud Run deploy step (see deploy.yml secrets: block)."
echo ""
echo "  Remaining secrets to add manually in GitHub:"
echo "    GEMINI_API_KEY        = (from aistudio.google.com)"
echo "    TWILIO_ACCOUNT_SID    = (from console.twilio.com)"
echo "    TWILIO_AUTH_TOKEN     = (from console.twilio.com)"
echo "    TWILIO_WHATSAPP_FROM  = whatsapp:+14155238886"
echo "    SALESPERSON_EMAIL     = your email"
echo "    CALENDAR_ID           = primary"
echo "    CLOUD_TASKS_QUEUE     = ${QUEUE_NAME}"
echo "    SMTP_HOST             = smtp.gmail.com"
echo "    SMTP_PORT             = 587"
echo "    SMTP_USER             = your-email@gmail.com"
echo "    SMTP_PASS             = your-app-password"
echo "    FROM_EMAIL            = noreply@realestate.ai"
echo ""
echo "  After adding all secrets, push to master or run the"
echo "  workflow manually from GitHub Actions to deploy. 🚀"

rm -f "${KEY_FILE}"
