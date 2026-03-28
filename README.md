# Apprise Notification Workflow Step

## Overview

This is a custom StackGuardian workflow step that sends notifications using [Apprise](https://github.com/caronc/apprise). It supports Jinja2 variable substitution in the title and body fields, allowing dynamic content based on workflow metadata and Terraform state outputs.

For more details on creating workflow steps, see the [StackGuardian documentation](https://docs.stackguardian.io/docs/develop/library/workflow_step/).

## Prerequisites

- An Apprise notification URL (see [Apprise URL Schemes](https://github.com/caronc/apprise#notification-services))

## Configuration Options

### apprise_url

- **Type**: string
- **Required**: Yes
- **Description**: The Apprise notification URL. Supports multiple protocols including:
  - `gotify://` - Gotify
  - `slack://` - Slack
  - `telegram://` - Telegram
  - `mailto://` - Email (SMTP)
  - `ntfy://` - Ntfy
  - And many more (see [Apprise documentation](https://github.com/caronc/apprise#notification-services))
- **Example**: `slack://webhook/abc123` or `gotify://token/url`

### title

- **Type**: string
- **Required**: Yes
- **Description**: Title for the notification. Supports Jinja2 variable substitution.
- **Default**: `Workflow Notification`
- **Available Variables**:
  - `workflow_name` - Name of the workflow
  - `run_id` - Unique run identifier
  - `run_url` - URL to the workflow run
  - `status` - Current workflow status
  - `triggered_by` - Who triggered the workflow
  - `artifact_path` - Path to workflow artifacts
  - `step_name` - Current step name
  - `step_status` - Current step status
  - `state.outputs.<key>` - Terraform state output values

### body

- **Type**: string
- **Required**: Yes
- **Description**: Body of the notification. Supports Jinja2 variable substitution.
- **Default**: `Workflow executed successfully`
- **Available Variables**: Same as `title`

## Terraform State Integration

This workflow step reads Terraform state from the workspace directory (set via `SG_MOUNTED_WORKSPACE_ROOT_DIR`). The state file is expected at `terraform.tfstate` in the workspace root.

### Accessing State Outputs

Use `state.outputs.<output_name>` in your Jinja2 templates:

```json
{
  "apprise_url": "slack://webhook/abc123",
  "title": "Deployment Complete",
  "body": "VPC ID: {{ state.outputs.vpc_id }}\nDatabase Host: {{ state.outputs.db_host }}"
}
```

**Note**: The Terraform workflow must have outputs defined in the `outputs` block of your `.tf` files.

## Example Usage

### Simple notification
```json
{
  "apprise_url": "slack://webhook/abc123",
  "title": "Workflow Complete",
  "body": "The workflow {{ workflow_name }} has finished running."
}
```

### Using Terraform state outputs
```json
{
  "apprise_url": "gotify://token/url",
  "title": "Infrastructure Deployed",
  "body": "VPC: {{ state.outputs.vpc_id }}\nSubnet: {{ state.outputs.subnet_id }}\nStatus: {{ status }}"
}
```

### Detailed status notification
```json
{
  "apprise_url": "slack://webhook/abc123",
  "title": "Deployment {{ status }}",
  "body": "Workflow: {{ workflow_name }}\nRun ID: {{ run_id }}\nTriggered by: {{ triggered_by }}\nStatus: {{ status }}\nURL: {{ run_url }}"
}
```

## Configuring a StackGuardian Workflow

To create a workflow using this step, you can use the StackGuardian Workflow as Code feature. For more details, see the [official documentation](https://docs.stackguardian.io/docs/deploy/workflows/create_workflow/json/#using-workflow-as-code).

```json
{
  "WfType": "CUSTOM",
  "WfStepsConfig": [
    {
      "name": "notify",
      "wfStepTemplateId": "/your-org/apprise-notification:1.0.0",
      "wfStepInputData": {
        "schemaType": "FORM_JSONSCHEMA",
        "data": {
          "apprise_url": "slack://webhook/abc123",
          "title": "Deployment {{ status }}",
          "body": "Workflow {{ workflow_name }} completed. VPC: {{ state.outputs.vpc_id }}"
        }
      },
      "approval": false,
      "timeout": 300
    }
  ]
}
```

## Building the Container

```bash
docker build -t ghcr.io/<owner>/sg-notification-wfs:latest .
```

## Testing Locally

```bash
# Set required environment variables
export BASE64_WORKFLOW_STEP_INPUT_VARIABLES=$(echo '{"apprise_url": "json://test", "title": "Test {{ workflow_name }}", "body": "State: {{ state.outputs.test_output }}"}' | base64)
export SG_MOUNTED_ARTIFACTS_DIR=/tmp/artifacts
export SG_MOUNTED_IAC_SOURCE_CODE_DIR=/tmp
export SG_MOUNTED_WORKSPACE_ROOT_DIR=/tmp/workspace
export BASE64_IAC_INPUT_VARIABLES=e30=
export SG_WORKFLOW_NAME="Test Workflow"
export SG_RUN_ID="12345"
export SG_RUN_URL="https://app.stackguardian.io/run/12345"
export SG_WORKFLOW_STATUS="success"
export SG_TRIGGERED_BY="user@example.com"
export SG_STEP_NAME="notify"
export SG_STEP_STATUS="success"

# Create mock terraform state
mkdir -p /tmp/artifacts /tmp/workspace
echo '{"outputs": {"vpc_id": "vpc-12345", "db_host": "db.example.com"}}' > /tmp/workspace/terraform.tfstate

python3 main.py
```