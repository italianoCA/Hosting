# mcp_server.py
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
import requests, base64, os
app = FastMCP("server")

app.settings.host = "0.0.0.0"
app.settings.port= 8089
app.settings.transport_security.enable_dns_rebinding_protection = False

#app = MCP("zoom_zva_diagnostics")

# Environment variables for credentials
load_dotenv()

ACCOUNT_ID = os.getenv("ZOOM_ACCOUNT_ID")
CLIENT_ID = os.getenv("ZOOM_CLIENT_ID")
CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET")

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