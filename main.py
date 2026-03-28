#!/usr/bin/env python3
"""
Apprise Notification Workflow Step for StackGuardian.

This workflow step sends notifications via Apprise with Jinja2 template support.
It can access Terraform state outputs from the workspace for dynamic notifications.

Environment Variables:
    - BASE64_WORKFLOW_STEP_INPUT_VARIABLES: Base64 encoded workflow step input params
    - SG_MOUNTED_ARTIFACTS_DIR: Directory for workflow artifacts
    - SG_MOUNTED_WORKSPACE_ROOT_DIR: Directory containing terraform state
    - SG_WORKFLOW_ID: Workflow ID path (e.g., /wfgrps/my-group/wfs/my-workflow)
    - SG_WORKFLOW_RUN_ID: Run ID path (e.g., /wfgrps/my-group/wfs/my-workflow/wfruns/run-id)
    - SG_EXECUTOR_USER: User who triggered the workflow
    - SG_STEP_NAME: Name of this workflow step
"""

import os
import sys
import json
import base64
from datetime import datetime

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

    try:
        decoded = base64.b64decode(encoded_input).decode("utf-8")
        params = json.loads(decoded)
    except Exception as e:
        err(f"Failed to decode workflow step input: {e}")

    required = ["apprise_url", "title", "body"]
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


def send_notification(url, title, body):
    """
    Send a notification via Apprise.

    Args:
        url: Apprise notification URL
        title: Notification title
        body: Notification body

    Returns:
        bool: True if notification sent successfully

    Raises:
        Exits with error if notification fails
    """

    app = apprise.Apprise()
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
    if not any(send_results or []):
        err("Failed to send notification")

    return True


def save_outputs(artifacts_dir, apprise_url):
    """
    Save workflow outputs and facts to artifacts directory.

    Args:
        artifacts_dir: Path to the artifacts directory
        apprise_url: The Apprise URL used for notification
    """
    timestamp = datetime.utcnow().isoformat() + "Z"

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
    info("Starting Apprise notification workflow step")
    debug(
        f"Inputs: apprise_url={params['apprise_url']}, title={params['title']}, body={params['body']}"
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
    }

    # Render title and body with Jinja2 templates
    rendered_title = render_template(params["title"], variables)
    rendered_body = render_template(params["body"], variables)

    info(f"Rendered title: {rendered_title}")
    debug(f"Rendered body: {rendered_body}")

    # Send the notification
    send_notification(params["apprise_url"], rendered_title, rendered_body)

    # Save outputs and facts for StackGuardian
    save_outputs(vars["artifacts_dir"], params["apprise_url"])

    info("Workflow step completed successfully")


if __name__ == "__main__":
    main()
