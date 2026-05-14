# Automation Intake Agent

A Glean conversational agent that replaces a manual intake form. Team members describe their automation request in plain language to a Glean AI assistant; the agent extracts all 19 structured fields via Gemini NLP and creates a formatted Asana task with custom fields and priority populated — no form-filling required.

## How it works

```
Team member → Glean AI conversation
                    ↓
         Glean Custom Action POST /execute
                    ↓
         Gemini 2.5 Flash (Vertex AI)
         extracts 19 structured fields
                    ↓
         Asana task created with:
           • Custom field: Request Type
           • Custom field: Priority (Tier 1/2/3)
           • Custom field: Requestor (resolved from name → user GID)
           • Structured HTML description with all 19 fields
           • Auto-gathered Glean context attached
```

## Fields extracted

Gemini NLP extracts these 19 fields from the conversation:

| Field | Type |
|---|---|
| Your Name | string |
| Request Type | New Automation / Improvement / Research / Engineering / Operations / Data |
| Automation Name | string |
| Business Justification / Priority | Tier 1 / Tier 2 / Tier 3 |
| Target Completion Date | date |
| Completion Date Justification | string |
| Stakeholders | string |
| Point of Contact | string |
| Process Description | string |
| Inputs | string |
| Outputs | string |
| Manual Process Frequency | Daily / Weekly / Monthly / Ad-hoc |
| Systems / Tools Required | string |
| System Access / Credentials Required | string |
| Sensitive Data Disclaimer | PII / No sensitive data / Unsure |
| Estimated Time Saved | string |
| User Stories / Success Story | string |
| Link to Manual Process Recording | URL |
| Relevant Documents | string |

Plus a `glean_context` field — any related docs, prior requests, or internal knowledge the Glean agent found during the conversation.

## Stack

- **Flask** + Gunicorn — lightweight webhook server
- **Gemini 2.5 Flash** via Vertex AI — NLP field extraction with JSON output mode
- **Asana API** — task creation with custom fields and user lookup
- **Glean Custom Actions** — OpenAPI schema defines the integration contract
- **Railway** — production deployment

## Setup

```bash
cp .env.example .env
# Fill in your Asana GIDs, GCP project, and service account
pip install -r requirements.txt
python3 app.py
```

### Getting Asana GIDs

1. Open your Asana project
2. Project settings → Custom Fields → click a field to get its GID from the URL
3. For enum option GIDs: use the Asana API — `GET /custom_fields/{field_gid}` returns all option GIDs

### Glean Custom Action setup

1. Deploy to Railway (or any HTTPS endpoint)
2. Update `servers.url` in `openapi.yaml` with your deployment URL
3. Register the OpenAPI spec as a Glean Custom Action in your Glean admin console
4. Create a Glean AI assistant that calls this action with the full conversation text

## API

### `POST /execute`

Accepts the Glean conversation payload and returns the created Asana task URL.

**Request:**
```json
{
  "User_message": "I need a new automation to sync our CRM leads to HubSpot daily. It's currently a manual export that takes 2 hours per week. Tier 2 priority. Contact: Sarah Johnson."
}
```

**Response:**
```json
{
  "status": "success",
  "message": "✅ Automation request submitted!\n\nTask: CRM to HubSpot Sync\nLink: https://app.asana.com/0/.../...",
  "task_url": "https://app.asana.com/0/...",
  "task_gid": "1234567890"
}
```

### `GET /health`

Returns `{"status": "ok"}`.
