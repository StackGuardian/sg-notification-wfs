#!/usr/bin/env bash
#
# Local test script for Apprise notification workflow step
#
# Tests two modes:
#   1. Standard mode - Jinja2 in title/body
#   2. Template mode - Custom JSON template (Adaptive Cards) with custom URL tokens
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/.venv/bin/activate"

TEMP_DIR=$(mktemp -d)
WORKSPACE_DIR="${TEMP_DIR}/workspace"
ARTIFACTS_DIR="${TEMP_DIR}/artifacts"

cleanup() {
    rm -rf "${TEMP_DIR}"
}
trap cleanup EXIT

mkdir -p "${WORKSPACE_DIR}" "${ARTIFACTS_DIR}"

# Terraform state with test outputs
cat > "${WORKSPACE_DIR}/terraform.tfstate" << 'EOF'
{
  "version": 4,
  "outputs": {
    "vpc_id": {"value": "vpc-0123456789abcdef", "type": "string"},
    "app_name": {"value": "my-webapp", "type": "string"},
    "region": {"value": "us-west-2", "type": "string"}
  }
}
EOF

export SG_MOUNTED_ARTIFACTS_DIR="${ARTIFACTS_DIR}"
export SG_MOUNTED_IAC_SOURCE_CODE_DIR="${TEMP_DIR}/iac"
export SG_MOUNTED_WORKSPACE_ROOT_DIR="${WORKSPACE_DIR}"
export SG_WORKFLOW_ID="/wfgrps/prod-group/wfs/webapp-deployment"
export SG_WORKFLOW_RUN_ID="/wfgrps/prod-group/wfs/webapp-deployment/wfruns/run-20240315-001"
export SG_EXECUTOR_USER="ci-bot@company.com"
export SG_STEP_NAME="notify"

# Replace with your actual Power Automate URL
APPRISE_URL="https://your-powerautomate-url.logic.azure.com/workflows/WFID/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=SIGNATURE"

echo "============================================"
echo "Test 1: Standard Notification (Jinja2 in title/body)"
echo "============================================"

TEMP_JSON=$(mktemp)
printf '{"apprise_url": "%s", "title": "Deploy {{ workflow_name }}", "body": "VPC: {{ state.outputs.vpc_id }}"}' "${APPRISE_URL}" > "${TEMP_JSON}"
export BASE64_WORKFLOW_STEP_INPUT_VARIABLES=$(base64 -w0 < "${TEMP_JSON}")
rm "${TEMP_JSON}"
python main.py

echo ""
echo "============================================"
echo "Test 2: Template Mode (Adaptive Card with custom URL tokens)"
echo "============================================"
echo "URL has :target={{ state.outputs.vpc_id }} which becomes {{ target }} in template"

TEMP_JSON=$(mktemp)
cat > "${TEMP_JSON}" << 'JSONEOF'
{
  "apprise_url": "%s&:target={{ state.outputs.vpc_id }}",
  "use_template": true,
  "template": {
    "type": "AdaptiveCard",
    "version": "1.5",
    "body": [
      {"type": "TextBlock", "text": "{{ app_title }}", "weight": "Bolder", "size": "Large"},
      {"type": "TextBlock", "text": "Hello {{ target }}, VPC {{ state.outputs.vpc_id }} is ready.", "wrap": true},
      {"type": "FactSet", "facts": [
        {"title": "App", "value": "{{ state.outputs.app_name }}"},
        {"title": "Region", "value": "{{ state.outputs.region }}"}
      ]}
    ]
  }
}
JSONEOF
sed -e "s|%s|${APPRISE_URL}|" "${TEMP_JSON}" | base64 -w0 > /tmp/template_encoded
export BASE64_WORKFLOW_STEP_INPUT_VARIABLES=$(cat /tmp/template_encoded)
rm "${TEMP_JSON}" /tmp/template_encoded
python main.py

echo ""
echo "All tests completed!"