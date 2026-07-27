# mcp_server.py
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import requests, base64, os
app = FastMCP("server")

app.settings.host = "0.0.0.0"
app.settings.port= 8089
app.settings.transport_security.enable_dns_rebinding_protection = False

#app = MCP("zoom_zva_diagnostics")

# Environment variables for credentials
load_dotenv()

ACCOUNT_ID = os.getenv("ZOOM_ACCOUNT_ID", "").strip().strip("'\"")
CLIENT_ID = os.getenv("ZOOM_CLIENT_ID", "").strip().strip("'\"")
CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET", "").strip().strip("'\"")

if not ACCOUNT_ID or not CLIENT_ID or not CLIENT_SECRET:
    raise ValueError("Missing Zoom credentials. Please set ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, and ZOOM_CLIENT_SECRET environment variables.")

def get_zoom_token(account_id, client_id, client_secret):
    url = f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={account_id}"
    auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth_header}"}

    #print ("#### URL: ", url)

    resp = requests.post(url, headers=headers)
    resp.raise_for_status()
    return resp.json()["access_token"]

def zoom_api_get(endpoint):
    token = get_zoom_token(ACCOUNT_ID, CLIENT_ID, CLIENT_SECRET)
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"https://api.zoom.us/v2/{endpoint}", headers=headers)
    print ("#### Status code: ", resp)
    #print ("#### JSON Response: ",resp.json())

    if resp.status_code != 200:
        raise RuntimeError(f"Zoom API error {resp.status_code}: {resp.text}")

    if not resp.text.strip():
        raise RuntimeError(f"Empty response from Zoom API for endpoint: {endpoint}")

    return resp.json()

@app.tool("get_contact_center_history", description="Retrieve Zoom Contact Center engagement history for a phone number within a 29-day safe window")
def get_contact_center_history(
    phone_number: str,
    from_date: str = None,
    to_date: str = None
):
    """
    Retrieve bundled engagement history from Zoom Contact Center.
    Uses a 29-day safe window to avoid API rate limiting.

    Args:
        phone_number: Consumer phone number to query (e.g., "+1234567890" or "1234567890")
        from_date: Optional start date in YYYY-MM-DD format (defaults to 29 days ago)
        to_date: Optional end date in YYYY-MM-DD format (defaults to today)

    Returns:
        Dictionary with engagement count, latest disposition, notes, and query window
    """

    # --- 1. THE AUTOMATIC CLOCK (Safe 29-Day Window) ---
    today = datetime.now(timezone.utc).date()

    if not to_date:
        to_date = today.isoformat()

    if not from_date:
        start_date = today - timedelta(days=29)
        from_date = start_date.isoformat()

    # --- 2. DATA VALIDATION ---
    if not phone_number or not phone_number.strip():
        return {"status": "Error", "detail": "Missing required phone_number"}

    # --- 3. CLEAN PHONE NUMBER ---
    cleaned = ''.join(c for c in phone_number if c.isdigit() or c == '+')
    final_phone = cleaned if cleaned.startswith('+') else '+' + cleaned
    encoded_phone = final_phone.replace('+', '%2B')

    try:
        # --- 4. AUTHENTICATION ---
        token = get_zoom_token(ACCOUNT_ID, CLIENT_ID, CLIENT_SECRET)

        # --- 5. API CALL ---
        api_url = 'https://api.zoom.us/v2/contact_center/engagements'
        final_url = f"{api_url}?from={from_date}&to={to_date}&consumer_number={encoded_phone}&page_size=100"
        print ("#### Final URL: ", final_url)

        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(final_url, headers=headers)

        if response.status_code != 200:
            return {"status": "Error", "code": response.status_code, "detail": response.text}

        data = response.json()
        print ("#### API Response: ", data)

        if not data.get("engagements") or len(data.get("engagements", [])) == 0:
            return {"status": "No History", "engagement_count": 0}

        # --- 6. PARSE DATA ---
        engagements = data.get("engagements", [])

        latest_engagement = engagements[0]
        latest_disposition = "N/A"
        latest_note = "No note recorded"

        if latest_engagement.get("dispositions") and len(latest_engagement["dispositions"]) > 0:
            latest_disposition = latest_engagement["dispositions"][0].get("disposition_name", "N/A")

        if latest_engagement.get("notes") and len(latest_engagement["notes"]) > 0:
            latest_note = latest_engagement["notes"][0].get("note", "No note recorded")

        all_notes = [
            e["notes"][0]["note"] if (e.get("notes") and len(e.get("notes", [])) > 0) else "N/A"
            for e in engagements
        ]

        result = {
            "status": "Success",
            "phone_number": final_phone,
            "engagement_count": len(engagements),
            "latest_disposition": latest_disposition,
            "latest_note": latest_note,
            "all_notes": all_notes,
            "query_window": {
                "from": from_date,
                "to": to_date
            }
        }

        return result

    except Exception as err:
        return {"status": "Error", "detail": str(err)}

@app.tool("get_zva_sessions", description="Retrieve Zoom Virtual Agent engagements within a date range and AI type")
def get_zva_sessions(
    start_date: str,  # e.g. "2025-12-01"
    end_date: str,    # e.g. "2025-12-18"
    ai_type: str = "ai_voice, ai_chat, chat",  # choose from ai_voice, ai_chat, ai_workplace
    limit: int = 10
):
    endpoint = (f"virtual_agent/report/engagements?from={start_date}&to={end_date}&timezone=UTC&page_size={limit}&agent_types={ai_type}")
    
    print ("#### Endpoint:", endpoint)
    data = zoom_api_get(endpoint)

    engagements = data.get("engagements", [])
    # Extract and print both engagement_id and agent_type
    engagement_info = [
        {
            "engagement_id": e.get("engagement_id"),
            "agent_type": e.get("agents", [{}])[0].get("agent_type") if e.get("agents") else None
        }
        for e in engagements
    ]

    print("#### Engagements (ID and Agent Type):", engagement_info)
    #print("#### Engagement IDs:", [e["engagement_id"] for e in data.get("engagements", [])])
    #print("#### Raw API response:", data)


    return {
        "start_date": f"{start_date}T00:00:00Z",
        "end_date": f"{end_date}T23:59:59Z",
        "engagements": data.get("engagements", [])
    }


@app.tool("get_zva_transcript", description="Retrieve transcript for a specific ZVA session within a date range and AI type")
def get_zva_transcript(
    engagement_ids: str,
    start_date: str,  # e.g. "2025-12-01"
    end_date: str,    # e.g. "2025-12-18"
    ai_type: str = "ai_voice",  # choose from ai_voice, ai_chat, ai_workplace
    limit: int = 10
):
    endpoint = (f"virtual_agent/report/engagements/query_details?from={start_date}T00:00:00Z&to={end_date}T23:59:59Z&timezone=UTC&page_size={limit}&agent_types={ai_type}&engagement_ids={engagement_ids}")
    
    #print("### Endpoint: ", endpoint)
    data = zoom_api_get(endpoint)
    #print("#### Engagement IDs:", [e["engagement_id"] for e in data.get("engagements", [])])
    return {
        "start_date": f"{start_date}T00:00:00Z",
        "end_date": f"{end_date}T23:59:59Z",
        "engagements": data.get("engagement_query_details", [])}

@app.tool("analyze_zva_behavior", description="Explain why ZVA gave a specific answer or failed within a date range and AI type")
def analyze_zva_behavior(
    engagement_ids: str,
    start_date: str,  # e.g. "2025-12-01"
    end_date: str,    # e.g. "2025-12-18"
    ai_type: str = "ai_voice",  # choose from ai_voice, ai_chat, ai_workplace
    limit: int = 10
):
    transcript = zoom_api_get(f"/virtual_agent/report/transcripts?from={start_date}T00:00:00Z&to={end_date}T23:59:59Z&timezone=UTC&page_size={limit}&agent_types={ai_type}&engagement_ids={engagement_ids}")
    variables = zoom_api_get(f"virtual_agent/report/engagements/variables?from={start_date}T00:00:00Z&to={end_date}T23:59:59Z&timezone=UTC&page_size={limit}&agent_types={ai_type}&engagement_ids={engagement_ids}")
    details = zoom_api_get(f"virtual_agent/report/engagements/query_details?from={start_date}T00:00:00Z&to={end_date}T23:59:59Z&timezone=UTC&page_size={limit}&agent_types={ai_type}&engagement_ids={engagement_ids}")
    
    print("### Transcript: ", transcript)
    print("### Variables: ", variables)
    print("### Details: ", details)
    #errors = zoom_api_get(f"contact_center/interactions/{interaction_id}/errors")

    summary = {
        "engagement_id": engagement_ids,
        "transcript": transcript.get("transcripts", []),
        "variables": variables.get("engagement_variable_details", []),
        "details": details.get("engagement_query_details", []),
        #"error_count": len(errors.get("errors", [])),
        "possible_causes": []
    }

    #if summary[transcript.get("total_records")] == 0:
        #summary["possible_causes"].append("No transcript found.")
    if not summary["variables"]:
        summary["possible_causes"].append("No variables found in transcript.")
    if  "fallback" in summary["details"]:
        summary["possible_causes"].append("Fallback intent triggered due to low confidence.")

    return summary

if __name__ == "__main__":
  app.run(transport="streamable-http")