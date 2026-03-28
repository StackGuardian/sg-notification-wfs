#!/usr/bin/env bash
#
# Local test script for Apprise notification workflow step
# Sets up mock environment and runs main.py
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate virtual environment
source "${SCRIPT_DIR}/.venv/bin/activate"

# Create temp directories
TEMP_DIR=$(mktemp -d)
WORKSPACE_DIR="${TEMP_DIR}/workspace"
ARTIFACTS_DIR="${TEMP_DIR}/artifacts"

cleanup() {
    rm -rf "${TEMP_DIR}"
}
trap cleanup EXIT

mkdir -p "${WORKSPACE_DIR}" "${ARTIFACTS_DIR}"

# Create mock terraform state
cat > "${WORKSPACE_DIR}/terraform.tfstate" << 'EOF'
{
  "version": 4,
  "outputs": {
    "vpc_id": {
      "value": "vpc-0123456789abcdef",
      "type": "string"
    },
    "subnet_ids": {
      "value": ["subnet-abc123", "subnet-def456"],
      "type": ["list", "string"]
    },
    "db_host": {
      "value": "db.prod.example.com",
      "type": "string"
    },
    "db_port": {
      "value": 5432,
      "type": "number"
    },
    "bucket_name": {
      "value": "my-app-bucket",
      "type": "string"
    }
  }
}
EOF

# Set base environment variables (common across all tests)
export SG_MOUNTED_ARTIFACTS_DIR="${ARTIFACTS_DIR}"
export SG_MOUNTED_IAC_SOURCE_CODE_DIR="${TEMP_DIR}/iac"
export SG_MOUNTED_WORKSPACE_ROOT_DIR="${WORKSPACE_DIR}"
export BASE64_IAC_INPUT_VARIABLES=e30=
export SG_WORKFLOW_ID="/wfgrps/prod-group/wfs/webapp-deployment"
export SG_WORKFLOW_RUN_ID="/wfgrps/prod-group/wfs/webapp-deployment/wfruns/run-20240315-001"
export SG_EXECUTOR_USER="ci-bot@company.com"
export SG_STEP_NAME="notify"

APPRISE_URL="discord://StackGuardian@1487411941566582908/bYgleidImGYUN3-_J2IPG39kHI98IA5gZc29ih3DK-ggxvLp5LXK9FzSmd6Y9-PTpgrY"

run_test() {
    local test_name="$1"
    local title="$2"
    local body="$3"

    echo "Test: ${test_name}"
    echo "---"

    # Create JSON file with test params
    local temp_json=$(mktemp)
    printf '{"apprise_url": "%s", "title": "%s", "body": "%s"}' \
        "${APPRISE_URL}" \
        "${title}" \
        "${body}" > "${temp_json}"

    export BASE64_WORKFLOW_STEP_INPUT_VARIABLES=$(base64 -w0 < "${temp_json}")
    rm "${temp_json}"

    python main.py
    echo ""
}

echo "============================================"
echo "Running Apprise Notification Tests"
echo "============================================"
echo ""

# Test 1: Full workflow metadata + terraform state
run_test \
    "Full workflow metadata + terraform state" \
    "Deployment {{ status }}" \
    "Workflow: {{ workflow_name }}\nRun: {{ run_id }}\nTriggered by: {{ triggered_by }}\nVPC: {{ state.outputs.vpc_id }}\nDB: {{ state.outputs.db_host }}"

# Test 2: Simplified template
run_test \
    "Simplified template" \
    "{{ workflow_name }} Complete" \
    "Status: {{ status }}"

# Test 3: Only state outputs
run_test \
    "Only state outputs" \
    "Infrastructure Ready" \
    "VPC: {{ state.outputs.vpc_id }}\nBuckets: {{ state.outputs.bucket_name }}"

# Test 4: Missing state file (graceful fallback)
rm "${WORKSPACE_DIR}/terraform.tfstate"
run_test \
    "Missing state file" \
    "No State Test" \
    "Workflow: {{ workflow_name }}"

echo "============================================"
echo "All tests completed!"
echo "============================================"
echo ""
echo "Generated output files:"
cat "${ARTIFACTS_DIR}/sg.outputs.json"
echo ""
cat "${ARTIFACTS_DIR}/sg.workflow_run_facts.json"