# Apprise Notification Workflow Step

## Overview

This is a custom StackGuardian workflow step that sends notifications using [Apprise](https://github.com/caronc/apprise). It supports Jinja2 variable substitution in the URL, title, and body fields, allowing dynamic content based on workflow metadata and Terraform state outputs. It also supports custom JSON templates for Microsoft Adaptive Cards and other workflow services.

For more details on creating workflow steps, see the [StackGuardian documentation](https://docs.stackguardian.io/docs/develop/library/workflow_step/).

## Token Types: Understanding {{ }} Brackets

This step uses **two types of template brackets** for different purposes:

### 1. Jinja2 Brackets `{{ }}` - Processed by this step before sending

These are rendered **first** by this workflow step. Use them for:
- Workflow variables: `{{ workflow_name }}`, `{{ run_id }}`, `{{ status }}`
- Terraform outputs: `{{ state.outputs.vpc_id }}`, `{{ state.outputs.db_host }}`
- Custom tokens from URL: `{{ target }}` (defined via `:target=value` in URL)
- In the URL itself: `https://...?:target={{ state.outputs.owner }}`

**Where Jinja2 brackets work:**
- ✅ In the `apprise_url` field
- ✅ In the `title` field
- ✅ In the `body` field  
- ✅ In the `template` field (for custom template tokens)
- ✅ In URL parameters using `:key=value` syntax

### 2. Apprise Brackets `{{ }}` - Processed by Apprise after we send

These are rendered **later** by Apprise's template system. Use them for:
- `{{ app_title }}` - The notification title
- `{{ app_body }}` - The notification body
- `{{ app_id }}` - Application identifier (default: "Apprise")
- `{{ app_desc }}` - Application description
- `{{ app_color }}` - Color for message type (hex code)
- `{{ app_type }}` - Message type (info, warning, success)
- `{{ app_image_url }}` - Image URL for message type
- `{{ app_url }}` - Apprise instance URL

**Where Apprise brackets work:**
- ✅ In the `template` field only (when using template mode)

### Summary Table

| Token | Source | Processed By | Works In |
|-------|--------|--------------|----------|
| `{{ workflow_name }}` | Workflow metadata | This step | URL, title, body, template |
| `{{ state.outputs.vpc_id }}` | Terraform state | This step | URL, title, body, template |
| `{{ target }}` | URL `:target=value` | This step | URL, title, body, template |
| `{{ app_title }}` | Notification title | Apprise | template only |
| `{{ app_body }}` | Notification body | Apprise | template only |
| `{{ app_color }}` | Message type | Apprise | template only |

## Configuration Options

### apprise_url

- **Type**: string
- **Required**: Yes
- **Description**: The Apprise notification URL. Supports Jinja2 variable substitution for dynamic URLs (e.g., custom tokens for Adaptive Cards). You can use `:key=value` parameters in the URL to define custom template tokens.
- **Jinja2 Support**: The URL itself can contain Jinja2 variables like `{{ state.outputs.my_value }}`
- **Custom URL Tokens**: Use `:key=value` syntax to pass custom tokens to templates (e.g., `:target={{ state.outputs.vpc_id }}`). These are first rendered by Jinja2, then available as `{{ target }}` in templates.
- **Example**: 
  - `slack://webhook/abc123`
  - `workflows://host/path?format=MARKDOWN&:target={{ state.outputs.vpc_id }}`
  - Direct Power Automate URL with Jinja2 tokens

### use_template

- **Type**: boolean
- **Required**: No
- **Default**: false
- **Description**: Enable to use a custom JSON template (e.g., Microsoft Adaptive Cards) for the notification body instead of the standard title/body fields.

### template

- **Type**: string
- **Required**: When `use_template` is true
- **Description**: JSON template for the notification. Supports both Jinja2 variables and Apprise template tokens.

### title

- **Type**: string
- **Required**: Yes (when `use_template` is false)
- **Description**: Title for the notification. Supports Jinja2 variable substitution and Markdown formatting.
- **Default**: `Workflow Notification`

### body

- **Type**: string
- **Required**: Yes (when `use_template` is false)
- **Description**: Body of the notification. Supports Jinja2 variable substitution and Markdown formatting.
- **Default**: `Workflow executed successfully`

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

## Example Usage

### Example 1: Standard Notification (Jinja2 in title/body)

```json
{
  "apprise_url": "slack://webhook/abc123",
  "title": "Deploy {{ workflow_name }}",
  "body": "VPC: {{ state.outputs.vpc_id }}"
}
```

This sends a simple notification with variables substituted:
- Title becomes: "Deploy webapp-deployment"
- Body becomes: "VPC: vpc-0123456789abcdef"

### Example 2: Template Mode (Adaptive Cards with custom URL tokens)

```json
{
  "apprise_url": "https://...workflows/WFID/...?:target={{ state.outputs.vpc_id }}&:app={{ state.outputs.app_name }}",
  "use_template": true,
  "title": "Infrastructure Ready",
  "body": "Please check the Adaptive Card for details.",
  "template": {
    "type": "AdaptiveCard",
    "version": "1.5",
    "body": [
      {"type": "TextBlock", "text": "{{ app_title }}", "weight": "Bolder", "size": "Large"},
      {"type": "TextBlock", "text": "Hello {{ target }}, your VPC is ready.", "wrap": true},
      {"type": "FactSet", "facts": [
        {"title": "App", "value": "{{ app }}"},
        {"title": "Region", "value": "{{ state.outputs.region }}"}
      ]}
    ]
  }
}
```

How this works:

1. **Jinja2 renders URL first:** `{{ state.outputs.vpc_id }}` → "vpc-abc123" → URL has `:target=vpc-abc123`
2. **Jinja2 renders URL first:** `{{ state.outputs.app_name }}` → "myapp" → URL has `:app=myapp`
3. **URL parameters become template tokens:** `:target=vpc-abc123` → `{{ target }}` in template
4. **`{{ app_title }}` comes from your input:** Apprise substitutes it with "Infrastructure Ready" (from the `title` field above)
5. **`{{ app_body }}` comes from your input:** Apprise would substitute it with "Please check..." (from the `body` field)

**Note:** Even in template mode, you still need to provide `title` and `body`. Apprise uses these as `{{ app_title }}` and `{{ app_body }}` in your template.

### Important: Body in Template Mode

When using template mode with `{{ app_body }}` in your template, be aware of how variable substitution works:

**What happens:**
1. You provide: `"body": "Workflow: {{ workflow_name }}"` with Jinja2 variables
2. Our step renders this body with Jinja2 → `"Workflow: webapp-deployment"` (correct)
3. But `{{ app_body }}` in the template receives the **raw** body string before Jinja2 rendering
4. Apprise substitutes `{{ app_body }}` with the raw string → brackets remain

**Solution:** In template mode, keep `body` simple or use Jinja2 directly in the template:

```json
{
  "use_template": true,
  "title": "Notification",
  "body": "Check details in the card below",
  "template": {
    "type": "AdaptiveCard",
    "body": [
      {"type": "TextBlock", "text": "{{ app_title }}"},
      {"type": "TextBlock", "text": "Workflow: {{ workflow_name }}\nRun: {{ run_id }}", "wrap": true}
    ]
  }
}
```

**Why:** The `{{ app_body }}` token passes the body as-is to Apprise, which doesn't understand Jinja2 variables. Use Jinja2 directly in the template for workflow variables.


## Configuring a StackGuardian Workflow

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
          "title": "Deployment Complete",
          "body": "Workflow {{ workflow_name }} completed. VPC: {{ state.outputs.vpc_id }}"
        }
      },
      "approval": false,
      "timeout": 300
    }
  ]
}
```

## Testing Locally

```bash
# Set required environment variables
export BASE64_WORKFLOW_STEP_INPUT_VARIABLES=$(echo '{"apprise_url": "json://test", "title": "Test {{ workflow_name }}", "body": "State: {{ state.outputs.test_output }}"}' | base64)
export SG_MOUNTED_ARTIFACTS_DIR=/tmp/artifacts
export SG_MOUNTED_IAC_SOURCE_CODE_DIR=/tmp
export SG_MOUNTED_WORKSPACE_ROOT_DIR=/tmp/workspace
export BASE64_IAC_INPUT_VARIABLES=e30=

# StackGuardian environment variables
export SG_WORKFLOW_ID="/wfgrps/my-group/wfs/test-workflow"
export SG_WORKFLOW_RUN_ID="/wfgrps/my-group/wfs/test-workflow/wfruns/run-12345"
export SG_EXECUTOR_USER="user@example.com"
export SG_STEP_NAME="notify"

# Create mock terraform state
mkdir -p /tmp/artifacts /tmp/workspace
echo '{"outputs": {"vpc_id": {"value": "vpc-12345", "type": "string"}}}' > /tmp/workspace/terraform.tfstate

python3 main.py
```

Or use the test script:
```bash
./test_local.sh
```

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

### Dependencies

| Library | License | URL |
|---------|---------|-----|
| Apprise | BSD-3-Clause | https://github.com/caronc/apprise |
| Jinja2 | BSD-3-Clause | https://github.com/pallets/jinja |
| Python | PSF | https://www.python.org/ |