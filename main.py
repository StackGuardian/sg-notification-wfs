#!/usr/bin/env python3
"""
Apprise Notification Workflow Step for StackGuardian.

This workflow step sends notifications via Apprise with Jinja2 template support.
It can access Terraform state outputs from the workspace for dynamic notifications.

Features:
    - Jinja2 variable substitution in URL, title, and body fields
    - Custom JSON templates for Microsoft Adaptive Cards and other workflow services
    - Custom tokens via :key=value URL parameters for template substitution
    - Terraform state output integration for dynamic content
    - Support for Microsoft Power Automate workflows and similar services

Environment Variables:
    - BASE64_WORKFLOW_STEP_INPUT_VARIABLES: Base64 encoded workflow step input params
    - SG_MOUNTED_ARTIFACTS_DIR: Directory for workflow artifacts
    - SG_MOUNTED_WORKSPACE_ROOT_DIR: Directory containing terraform state
    - SG_WORKFLOW_ID: Workflow ID path (e.g., /wfgrps/my-group/wfs/my-workflow)
    - SG_WORKFLOW_RUN_ID: Run ID path (e.g., /wfgrps/my-group/wfs/my-workflow/wfruns/run-id)
    - SG_EXECUTOR_USER: User who triggered the workflow
    - SG_STEP_NAME: Name of this workflow step

Input Parameters (JSON):
    - apprise_url (required): The notification URL, supports Jinja2 variables
    - use_template (optional): Enable custom JSON template mode
    - template (optional): JSON template for notifications (when use_template=true)
    - title (optional): Notification title (required when not using template)
    - body (optional): Notification body (required when not using template)

Available Jinja2 Variables:
    - workflow_name: Name of the workflow
    - run_id: Run identifier
    - run_url: URL to the workflow run
    - status: Current workflow status
    - triggered_by: User who triggered the workflow
    - step_name: Current step name
    - step_status: Current step status
    - state.outputs.<key>: Terraform state output values

Template Tokens:
    Custom tokens can be defined in the URL using :key=value syntax.
    These are first rendered with Jinja2, then available as {{ key }} in templates.
    Example URL: "...?format=MARKDOWN&:target={{ state.outputs.owner }}"
"""

import os
import sys
import json
import base64
import re
import tempfile
import logging
from datetime import datetime, timezone

import apprise
from jinja2 import Template


def log_date():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")


def err(message):
    """Print error message and exit with code 1."""
    print(f"\n--- ERROR ---", file=sys.stderr)
    print(f"\033[38;5;196m{message}", file=sys.stderr)
    print(f"\n_____________\n", file=sys.stderr)
    sys.exit(1)


def info(message):
    """Print info message with green styling."""
    print(f"\n--- INFO ---")
    print(f"\033[32m{message}")
    print(f"\n____________\n")


def debug(message):
    """Print debug message."""
    print(f"[SG_DEBUG] {message}")


def warn(message):
    """Print warning message with yellow styling."""
    print(f"\n--- WARNING ---")
    print(f"\033[33m{message}\033[0m")
    print(f"\n_______________\n")


def parse_variables():
    """Parse StackGuardian environment variables."""
    debug("Listing available SG_* environment variables:")
    sg_vars = {k: v for k, v in os.environ.items() if k.startswith("SG_")}
    for key in sorted(sg_vars.keys()):
        debug(f"  {key}={sg_vars[key][:80]}...")

    return {
        "working_dir": os.environ.get("SG_MOUNTED_IAC_SOURCE_CODE_DIR", ""),
        "artifacts_dir": os.environ.get("SG_MOUNTED_ARTIFACTS_DIR", ""),
        "workspace_root": os.environ.get("SG_MOUNTED_WORKSPACE_ROOT_DIR", ""),
        "step_input": os.environ.get("BASE64_WORKFLOW_STEP_INPUT_VARIABLES", ""),
        "iac_input": os.environ.get("BASE64_IAC_INPUT_VARIABLES", ""),
    }


def process_workflow_inputs(encoded_input):
    """
    Decode and validate workflow step input parameters.

    Args:
        encoded_input: Base64 encoded JSON string of input parameters

    Returns:
        dict: Decoded and validated input parameters

    Raises:
        Exits with error if validation fails
    """
    if not encoded_input:
        err("BASE64_WORKFLOW_STEP_INPUT_VARIABLES not set")

    params = {}
    try:
        decoded = base64.b64decode(encoded_input).decode("utf-8")
        params = json.loads(decoded)
    except Exception as e:
        err(f"Failed to decode workflow step input: {e}")

    required = ["apprise_url"]
    if not params.get("use_template"):
        required.extend(["title", "body"])
    for field in required:
        if not params.get(field):
            err(f"{field} is required but not provided")

    return params


def get_workflow_metadata():
    """
    Retrieve workflow metadata from StackGuardian environment variables.

    StackGuardian provides workflow identifiers as paths, not human-readable names.
    We derive what we can from the available environment variables.
    """
    # SG_WORKFLOW_ID format: /wfgrps/<group>/wfs/<workflow>
    # SG_WORKFLOW_RUN_ID format: /wfgrps/<group>/wfs/<workflow>/wfruns/<run>
    workflow_id = os.environ.get("SG_WORKFLOW_ID", "")
    run_id = os.environ.get("SG_WORKFLOW_RUN_ID", "")
    executor = os.environ.get("SG_EXECUTOR_USER", "")
    step_name = os.environ.get("SG_STEP_NAME", "")

    # Extract workflow name from path (last component)
    workflow_name = "unknown"
    if workflow_id:
        parts = workflow_id.rstrip("/").split("/")
        # Path format: /wfgrps/<group>/wfs/<name>
        if "wfs" in parts:
            idx = parts.index("wfs")
            if idx + 1 < len(parts):
                workflow_name = parts[idx + 1]

    # Extract run ID from path
    run_id_short = "unknown"
    if run_id:
        parts = run_id.rstrip("/").split("/")
        # Path format: /wfgrps/<group>/wfs/<name>/wfruns/<id>
        if "wfruns" in parts:
            idx = parts.index("wfruns")
            if idx + 1 < len(parts):
                run_id_short = parts[idx + 1]

    # Construct run URL (approximate - this may vary by deployment)
    run_url = f"https://app.stackguardian.io/run/{run_id_short}"

    return {
        "workflow_name": workflow_name,
        "run_id": run_id_short,
        "run_url": run_url,
        "status": "completed",  # If we're running, status is at least "completed"
        "triggered_by": executor,
        "step_name": step_name,
        "step_status": "success",
    }


def load_terraform_state(workspace_dir):
    """
    Load terraform state outputs from workspace directory.

    Looks for terraform.tfstate or terraform.tfstate.backup in the workspace
    and extracts the outputs for use in Jinja2 templates.

    Args:
        workspace_dir: Path to the workspace root directory

    Returns:
        dict: Terraform state outputs keyed by output name
    """
    if not workspace_dir or not os.path.isdir(workspace_dir):
        return {}

    # Check for terraform state files
    tfstate_file = None
    for filename in ["terraform.tfstate", "terraform.tfstate.backup"]:
        path = os.path.join(workspace_dir, filename)
        if os.path.isfile(path):
            tfstate_file = path
            break

    if not tfstate_file:
        debug("No terraform state file found")
        return {}

    debug(f"Found terraform state file: {tfstate_file}")

    try:
        with open(tfstate_file, "r") as f:
            state = json.load(f)

        outputs = state.get("outputs", {})
        result = {}
        for key, value in outputs.items():
            # Handle both new and old terraform state format
            # New: {"outputs": {"key": {"value": "...", "type": "..."}}}
            # Old: {"outputs": {"key": "..."}}
            if isinstance(value, dict) and "value" in value:
                result[key] = value["value"]
            else:
                result[key] = value

        return result
    except Exception as e:
        debug(f"Error loading terraform state: {e}")
        return {}


def render_template(template_str, variables):
    """
    Render a Jinja2 template with the provided variables.

    Args:
        template_str: Jinja2 template string
        variables: Dictionary of variables for template rendering

    Returns:
        str: Rendered template

    Raises:
        Exits with error if rendering fails
    """
    try:
        t = Template(template_str)
        return t.render(**variables)
    except Exception as e:
        err(f"Failed to render template: {e}")


def send_notification(url, title, body, template_content=None, template_variables=None):
    """
    Send a notification via Apprise.

    Args:
        url: Apprise notification URL
        title: Notification title
        body: Notification body
        template_content: Optional JSON template content for workflow services

    Returns:
        bool: True if notification sent successfully

    Raises:
        Exits with error if notification fails
    """

    app = apprise.Apprise()

    # Enable debug logging for Apprise
    logging.getLogger("apprise").setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    logging.getLogger("apprise").addHandler(handler)

    template_path = None

    if template_content and template_variables:
        # Render template with template_variables to substitute custom tokens like {{ target }}, {{ vpc_id }}
        template_content = render_template(template_content, template_variables)
        debug(f"Rendered template with custom tokens: {len(template_content)} chars")

    if template_content:
        # Handle both string and dict template content
        if isinstance(template_content, dict):
            template_content = json.dumps(template_content)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(template_content)
            template_path = f.name

        # Append template parameter to URL
        if "?" in url:
            url = f"{url}&template={template_path}"
        else:
            url = f"{url}?template={template_path}"
        debug(f"Using template file: {template_path}")

    result = app.add(url)

    if not result:
        err(f"Failed to add URL: {url}")

    # Use MARKDOWN format for body and title
    send_results = app.notify(
        title=title,
        body=body,
        body_format=apprise.NotifyFormat.MARKDOWN,
        interpret_escapes=True,
    )

    # Handle both single bool and list of results
    if send_results is True:
        return True
    if send_results is False:
        err("Failed to send notification")

    # If it's a list, check if any succeeded
    if isinstance(send_results, list) and not any(send_results or []):
        err("Failed to send notification")

    # Cleanup temp template file
    if template_path:
        try:
            os.unlink(template_path)
            debug(f"Cleaned up template file: {template_path}")
        except Exception as e:
            warn(f"Failed to cleanup template file: {e}")

    return True


def save_outputs(artifacts_dir, apprise_url):
    """
    Save workflow outputs and facts to artifacts directory.

    Args:
        artifacts_dir: Path to the artifacts directory
        apprise_url: The Apprise URL used for notification
    """
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Save workflow outputs for downstream steps
    outputs = {
        "notification_sent": True,
        "apprise_url": apprise_url,
        "timestamp": timestamp,
    }

    outputs_file = os.path.join(artifacts_dir, "sg.outputs.json")
    with open(outputs_file, "w") as f:
        json.dump(outputs, f, indent=2)
    debug(f"Saved outputs to {outputs_file}")

    # Save workflow facts for auditing
    facts = {
        "notification": {
            "timestamp": timestamp,
            "status": "success",
            "apprise_url": apprise_url,
        }
    }

    facts_file = os.path.join(artifacts_dir, "sg.workflow_run_facts.json")
    with open(facts_file, "w") as f:
        json.dump(facts, f, indent=2)
    debug(f"Saved workflow facts to {facts_file}")


def main():
    """Main entry point for the workflow step."""
    # Parse environment variables
    vars = parse_variables()

    # Process and validate workflow inputs
    params = process_workflow_inputs(vars["step_input"])
    use_template = params.get("use_template", False)
    info("Starting Apprise notification workflow step")
    debug(f"Inputs: apprise_url={params['apprise_url']}, use_template={use_template}")

    if use_template:
        debug(
            f"Template content provided: {len(params.get('template', ''))} characters"
        )

    # Get workflow metadata
    metadata = get_workflow_metadata()
    debug(f"Workflow metadata: {metadata}")

    # Load terraform state outputs if available
    terraform_outputs = load_terraform_state(vars["workspace_root"])
    if terraform_outputs:
        debug(f"Terraform outputs: {terraform_outputs}")

    # Build variables for Jinja2 template rendering
    variables = {
        **metadata,
        "artifact_path": vars["artifacts_dir"],
        "state": {"outputs": terraform_outputs},
        # Include Apprise standard tokens for template substitution
        "app_title": params.get("title", "Notification"),
        "app_body": params.get("body", " ")
        if not use_template or params.get("body")
        else " ",
        "app_type": "info",
        "app_color": "#0078D4",
    }

    # Render title and body with Jinja2 templates
    # When using template mode, ensure body is not empty (required by Apprise for template substitution)
    if use_template and not params.get("body"):
        rendered_body = " "  # Single space as placeholder for template substitution
    else:
        rendered_body = render_template(params.get("body", ""), variables)

    rendered_title = render_template(params.get("title", "Notification"), variables)

    info(f"Rendered title: {rendered_title}")
    debug(f"Rendered body: {rendered_body}")

    # Render URL with Jinja2 template support (needed for Microsoft Adaptive Cards workflows)
    rendered_url = render_template(params["apprise_url"], variables)
    debug(f"Rendered URL: {rendered_url}")

    # Extract custom URL parameters (e.g., :target, :vpc_id) for template substitution
    # These are set via :key=value in the URL and consumed by Apprise's template system
    # Pattern matches :key=value until the next :key or end of query string
    url_vars = {}
    raw_url = params["apprise_url"]
    for match in re.finditer(r":(\w+)=", raw_url):
        key = match.group(1)
        start = match.end()
        # Find the end of this value (next :key= or end of URL/query string)
        next_match = re.search(r":\w+=", raw_url[start:])
        if next_match:
            end = start + next_match.start()
        else:
            # Find end of query string or end of URL
            end = len(raw_url)
        value = raw_url[start:end].split("&")[0]  # Stop at & params
        # Render the value with Jinja2 to resolve any nested variables
        try:
            value = render_template(value, variables)
        except Exception:
            pass  # Keep original value if rendering fails
        url_vars[key] = value
    debug(f"URL custom variables: {url_vars}")

    # Add URL variables to the template variables (for custom tokens in template)
    template_variables = {**variables, **url_vars}

    # Send the notification
    template_raw = params.get("template")
    if use_template:
        # Handle both dict and string template content
        if isinstance(template_raw, dict):
            template_content = json.dumps(template_raw)
        elif isinstance(template_raw, str):
            template_content = template_raw
        else:
            template_content = None
        debug(
            f"Template content: {len(template_content) if template_content else 0} characters"
        )
    else:
        template_content = None
    send_notification(
        rendered_url,
        rendered_title,
        rendered_body,
        template_content,
        template_variables,
    )

    # Save outputs and facts for StackGuardian
    save_outputs(vars["artifacts_dir"], params["apprise_url"])

    info("Workflow step completed successfully")


if __name__ == "__main__":
    main()
