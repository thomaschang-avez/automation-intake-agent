"""
app.py — AUTOMATION INTAKE AGENT
Flask webhook that accepts a POST /execute from Glean Actions, extracts
structured automation request fields via Gemini NLP, and creates a
formatted Asana task with custom fields populated.

Run locally: python3 app.py
Production:  gunicorn app:app
"""

from flask import Flask, request, jsonify
import json
import os
import html
import httpx
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
from google.oauth2 import service_account

app = Flask(__name__)

# ── ENVIRONMENT VARIABLES ──
ASANA_TOKEN = os.environ["ASANA_TOKEN"]

# ── ASANA PROJECT CONFIG ──
# Project: "Automation Requests & Opportunities (From Teamwork)"
ASANA_PROJECT_ID = os.environ.get("ASANA_PROJECT_ID", "")

# Custom field GIDs for this project
CUSTOM_FIELD_REQUEST_TYPE = os.environ.get("ASANA_FIELD_REQUEST_TYPE", "")
CUSTOM_FIELD_PRIORITY = os.environ.get("ASANA_FIELD_PRIORITY", "")
CUSTOM_FIELD_REQUESTOR = os.environ.get("ASANA_FIELD_REQUESTOR", "")

# Workspace GID for user lookup
ASANA_WORKSPACE_ID = os.environ.get("ASANA_WORKSPACE_ID", "")

# Request Type enum values
REQUEST_TYPE_MAP = {
    "New Automation": os.environ.get("ASANA_OPT_NEW_AUTOMATION", ""),
    "Automation Improvement/Fix": os.environ.get("ASANA_OPT_IMPROVEMENT", ""),
    "Research": os.environ.get("ASANA_OPT_RESEARCH", ""),
    "Engineering": os.environ.get("ASANA_OPT_ENGINEERING", ""),
    "Operations": os.environ.get("ASANA_OPT_OPERATIONS", ""),
    "Data Connection/Source": os.environ.get("ASANA_OPT_DATA_SOURCE", ""),
}

# Priority enum values
PRIORITY_MAP = {
    "Tier 1": os.environ.get("ASANA_OPT_TIER1", ""),   # Critical
    "Tier 2": os.environ.get("ASANA_OPT_TIER2", ""),   # High
    "Tier 3": os.environ.get("ASANA_OPT_TIER3", ""),   # Medium
}

# ── GEMINI SETUP WITH VERTEXAI ──
GEMINI_PROJECT = os.environ.get("GEMINI_PROJECT", "your-gcp-project-id")
GEMINI_LOCATION = "us-central1"

# Parse service account JSON from env
service_account_json = json.loads(os.environ["GCP_SERVICE_ACCOUNT"])

# Create credentials with cloud-platform scope
creds = service_account.Credentials.from_service_account_info(
    service_account_json,
    scopes=["https://www.googleapis.com/auth/cloud-platform"],
)

# Initialize Vertex AI with credentials
vertexai.init(
    project=GEMINI_PROJECT,
    location=GEMINI_LOCATION,
    credentials=creds,
)

# Initialize model
model = GenerativeModel("gemini-2.5-flash")

def lookup_asana_user(name):
    """Search Asana workspace for a user by name, return their GID or None."""
    if not name or name.strip() in ('Not provided', 'null', 'None'):
        return None
    resp = httpx.get(
        f"https://app.asana.com/api/1.0/workspaces/{ASANA_WORKSPACE_ID}/typeahead",
        headers={"Authorization": f"Bearer {ASANA_TOKEN}"},
        params={"resource_type": "user", "query": name.strip(), "count": 1},
        timeout=10,
    )
    if resp.status_code == 200:
        results = resp.json().get("data", [])
        if results:
            return results[0]["gid"]
    return None

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

@app.route('/execute', methods=['POST'])
def execute():
    try:
        data = request.get_json()
        user_message = data.get("User_message")

        if not user_message:
            return jsonify({"error": "missing required parameter: User_message", "gleanErrorCode": "ACTIONS_MISSING_REQUIRED_PARAMS"}), 400

        # ── GEMINI EXTRACTION ──
        prompt = f"""Extract automation request fields from this message. Return ONLY valid JSON.

Message: {user_message}

Extract these 20 fields (use null if not mentioned):
{{
  "your_name": "string",
  "request_type": "New Automation|Automation Improvement/Fix|Research|Engineering|Operations|Data Connection/Source",
  "automation_name": "string",
  "business_justification_priority": "Tier 1|Tier 2|Tier 3",
  "target_completion_date": "YYYY-MM-DD or null",
  "completion_date_justification": "string or null",
  "stakeholders": "string",
  "point_of_contact": "string",
  "process_description": "string",
  "inputs": "string",
  "outputs": "string",
  "manual_process_frequency": "Daily|Weekly|Monthly|Ad-hoc",
  "systems_tools_required": "string",
  "system_access_credentials_required": "string describing what's needed, or 'Not sure' or 'None'",
  "sensitive_data_disclaimer": "This process requires handling sensitive data (PII, Confidential data, etc.)|This process does not require handling sensitive data|Unsure",
  "estimated_time_saved": "string",
  "user_stories_success_story": "string describing user stories, success criteria, or what success looks like for this automation, or null",
  "link_to_manual_process_recording": "URL or null",
  "relevant_documents": "string or null",
  "notes": "string or null",
  "glean_context": "string summarizing any additional context provided by the agent such as related documents, existing processes, prior automation requests, or internal knowledge found via search. null if none provided"
}}"""

        generation_config = GenerationConfig(
            temperature=0.2,
            response_mime_type="application/json"
        )

        response = model.generate_content(
            prompt,
            generation_config=generation_config
        )

        extracted = json.loads(response.text)
        if isinstance(extracted, list):
            merged = {}
            for item in extracted:
                merged.update(item)
            extracted = merged

        # ── BUILD ASANA TASK DESCRIPTION ──
        def add_field(label, value):
            """Safely add a field with HTML escaping"""
            if value and str(value).strip() and str(value) not in ('Not provided', 'null', 'None'):
                safe_value = html.escape(str(value))
            else:
                safe_value = 'Not provided'
            return f"<strong>{label}:</strong>\n{safe_value}\n\n"

        description_parts = ["<body>"]
        description_parts.append(add_field("Your Name", extracted.get('your_name')))
        description_parts.append(add_field("Request Type", extracted.get('request_type')))
        description_parts.append(add_field("Automation Name", extracted.get('automation_name')))
        description_parts.append(add_field("Business Justification/Priority", extracted.get('business_justification_priority')))
        description_parts.append(add_field("Target Completion Date", extracted.get('target_completion_date')))
        description_parts.append(add_field("Completion Date Justification", extracted.get('completion_date_justification')))
        description_parts.append(add_field("Stakeholder(s)", extracted.get('stakeholders')))
        description_parts.append(add_field("Point of Contact", extracted.get('point_of_contact')))
        description_parts.append(add_field("Process Description", extracted.get('process_description')))
        description_parts.append(add_field("Inputs", extracted.get('inputs')))
        description_parts.append(add_field("Outputs", extracted.get('outputs')))
        description_parts.append(add_field("Manual Process Frequency", extracted.get('manual_process_frequency')))
        description_parts.append(add_field("Systems/Tools Required", extracted.get('systems_tools_required')))
        description_parts.append(add_field("System Access/Credentials Required", extracted.get('system_access_credentials_required')))
        description_parts.append(add_field("Sensitive Data Disclaimer", extracted.get('sensitive_data_disclaimer')))
        description_parts.append(add_field("Estimated Time Saved", extracted.get('estimated_time_saved')))
        description_parts.append(add_field("User Stories/Success Story", extracted.get('user_stories_success_story')))
        description_parts.append(add_field("Link to Manual Process Recording", extracted.get('link_to_manual_process_recording')))
        description_parts.append(add_field("Relevant Documents", extracted.get('relevant_documents')))
        description_parts.append(add_field("Notes", extracted.get('notes')))

        glean_context = extracted.get('glean_context')
        if glean_context and str(glean_context).strip() and str(glean_context) not in ('null', 'None', 'Not provided'):
            description_parts.append("\n<strong>━━━ Related Internal Context (Auto-gathered) ━━━</strong>\n\n")
            description_parts.append(f"{html.escape(str(glean_context))}\n\n")

        description_parts.append("</body>")

        description = "".join(description_parts)

        # ── BUILD CUSTOM FIELDS ──
        custom_fields = {}

        request_type = extracted.get("request_type")
        if request_type and request_type in REQUEST_TYPE_MAP:
            custom_fields[CUSTOM_FIELD_REQUEST_TYPE] = REQUEST_TYPE_MAP[request_type]

        priority = extracted.get("business_justification_priority")
        if priority and priority in PRIORITY_MAP:
            custom_fields[CUSTOM_FIELD_PRIORITY] = PRIORITY_MAP[priority]

        requestor_name = extracted.get("your_name")
        requestor_gid = lookup_asana_user(requestor_name)
        if requestor_gid:
            custom_fields[CUSTOM_FIELD_REQUESTOR] = [requestor_gid]

        # ── CREATE ASANA TASK ──
        task_payload = {
            "data": {
                "name": extracted.get("automation_name", "Automation Request"),
                "html_notes": description,
                "projects": [ASANA_PROJECT_ID],
            }
        }

        if custom_fields:
            task_payload["data"]["custom_fields"] = custom_fields

        asana_response = httpx.post(
            "https://app.asana.com/api/1.0/tasks",
            headers={
                "Authorization": f"Bearer {ASANA_TOKEN}",
                "Content-Type": "application/json"
            },
            json=task_payload,
            timeout=30
        )

        asana_response.raise_for_status()
        task_data = asana_response.json()["data"]
        task_gid = task_data["gid"]
        task_url = f"https://app.asana.com/0/{ASANA_PROJECT_ID}/{task_gid}"

        return jsonify({
            "status": "success",
            "message": f"✅ Automation request submitted!\n\nTask: {extracted.get('automation_name', 'Automation Request')}\nLink: {task_url}",
            "task_url": task_url,
            "task_gid": task_gid
        }), 200

    except json.JSONDecodeError as e:
        return jsonify({"error": f"Invalid JSON in Gemini response: {str(e)}"}), 500
    except httpx.HTTPStatusError as e:
        return jsonify({"error": f"Asana API error: {e.response.text}"}), 500
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
