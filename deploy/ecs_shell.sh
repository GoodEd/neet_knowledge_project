#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <region> <cluster-name> <service-name> [container-name]"
  echo "Example: $0 ap-south-1 np-pgrest neet-prod-worker worker"
  exit 1
fi

REGION="$1"
CLUSTER="$2"
SERVICE="$3"
CONTAINER="${4:-}"

TASK_ARN="$(aws ecs list-tasks \
  --region "$REGION" \
  --cluster "$CLUSTER" \
  --service-name "$SERVICE" \
  --desired-status RUNNING \
  --query 'taskArns[0]' \
  --output text)"

if [[ -z "$TASK_ARN" || "$TASK_ARN" == "None" ]]; then
  echo "No running task found for service: $SERVICE"
  exit 2
fi

CMD=(aws ecs execute-command
  --region "$REGION"
  --cluster "$CLUSTER"
  --task "$TASK_ARN"
  --interactive
  --command "/bin/sh")

if [[ -n "$CONTAINER" ]]; then
  CMD+=(--container "$CONTAINER")
fi

echo "Connecting to task: $TASK_ARN"
"${CMD[@]}"
