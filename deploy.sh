#!/bin/bash
# SAM Scraper — Cloud Run Deployment Script
# Run this after getting Cloud Run Admin + Cloud Build Editor access
#
# Usage: ./deploy.sh

set -e

PROJECT="apna-mart-data"
REGION="asia-south1"
IMAGE="gcr.io/${PROJECT}/sam-scraper"
JOB_NAME="sam-daily"
SCHEDULE="30 8 * * *"  # 8:30 AM IST daily

echo "═══════════════════════════════════════"
echo "  SAM Scraper — Cloud Run Deployment"
echo "═══════════════════════════════════════"

# Step 0: Set project
echo ""
echo "Step 0: Setting project..."
gcloud config set project ${PROJECT}
gcloud config set run/region ${REGION}

# Step 3: Build + push image to Google Container Registry
echo ""
echo "Step 3: Building Docker image on cloud..."
echo "  (This will take ~5-10 min on first build)"
gcloud builds submit --tag ${IMAGE} --timeout=1200

# Step 4: Create Cloud Run Job
echo ""
echo "Step 4: Creating Cloud Run Job..."
gcloud run jobs create ${JOB_NAME} \
  --image ${IMAGE} \
  --memory 4Gi \
  --cpu 2 \
  --timeout 14400 \
  --max-retries 1 \
  --region ${REGION} \
  --set-env-vars "METABASE_API_KEY=${METABASE_API_KEY},SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN}" \
  2>/dev/null || \
gcloud run jobs update ${JOB_NAME} \
  --image ${IMAGE} \
  --memory 4Gi \
  --cpu 2 \
  --timeout 14400 \
  --max-retries 1 \
  --region ${REGION} \
  --set-env-vars "METABASE_API_KEY=${METABASE_API_KEY},SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN}"

echo "  ✅ Job '${JOB_NAME}' ready"

# Step 5: Create Cloud Scheduler (daily 8:30 AM IST)
echo ""
echo "Step 5: Setting up daily schedule (${SCHEDULE} IST)..."

# Get the job URI for scheduler
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB_NAME}:run"

# Create scheduler (or update if exists)
gcloud scheduler jobs create http ${JOB_NAME}-cron \
  --schedule="${SCHEDULE}" \
  --time-zone="Asia/Kolkata" \
  --uri="${JOB_URI}" \
  --http-method=POST \
  --oauth-service-account-email="${PROJECT}@appspot.gserviceaccount.com" \
  --location=${REGION} \
  2>/dev/null || \
gcloud scheduler jobs update http ${JOB_NAME}-cron \
  --schedule="${SCHEDULE}" \
  --time-zone="Asia/Kolkata" \
  --uri="${JOB_URI}" \
  --http-method=POST \
  --oauth-service-account-email="${PROJECT}@appspot.gserviceaccount.com" \
  --location=${REGION}

echo "  ✅ Scheduled: ${SCHEDULE} IST (Asia/Kolkata)"

echo ""
echo "═══════════════════════════════════════"
echo "  DEPLOYMENT COMPLETE"
echo "═══════════════════════════════════════"
echo ""
echo "  Image:    ${IMAGE}"
echo "  Job:      ${JOB_NAME}"
echo "  Schedule: Daily 8:30 AM IST"
echo "  Region:   ${REGION}"
echo ""
echo "  Manual test run:"
echo "    gcloud run jobs execute ${JOB_NAME} --region ${REGION}"
echo ""
echo "  Check logs:"
echo "    gcloud run jobs executions list --job ${JOB_NAME} --region ${REGION}"
echo "    gcloud logging read 'resource.type=cloud_run_job' --limit 50"
echo ""
