# mcp_server.py - Zoom Virtual Agent MCP Server
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
import requests, base64, os, logging

# Load environment variables
load_dotenv()

# Initialize FastMCP server
app = FastMCP("Zoom Virtual Agent Server")

# Configure Server Settings — read PORT from Render environment, default to 8086
app.settings.host = "0.0.0.0"
app.settings.port = int(os.environ.get("PORT", 8089))
app.settings.transport_security.enable_dns_rebinding_protection = False

# Environment variables for Zoom credentials
ZOOM_ACCOUNT_ID = os.getenv("ZOOM_ACCOUNT_ID")
ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET")
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mcp-zoom-zva")

if not ZOOM_ACCOUNT_ID or not ZOOM_CLIENT_ID or not ZOOM_CLIENT_SECRET:
    logger.error("Missing Zoom credentials. Please set ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, and ZOOM_CLIENT_SECRET environment variables.")
    raise ValueError("Missing Zoom credentials. Please set ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, and ZOOM_CLIENT_SECRET environment variables.")

def validate_auth_token(token: str) -> bool:
    """Validate bearer token for API access. If MCP_AUTH_TOKEN not set, skip auth (dev mode)."""
    if not MCP_AUTH_TOKEN:
        logger.warning("MCP_AUTH_TOKEN not set — running in unauthenticated mode")
        return True
    return token.strip() == MCP_AUTH_TOKEN.strip()

def get_zoom_token(account_id, client_id, client_secret):
    """Get Zoom OAuth token using account credentials."""
    url = f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={account_id}"
    auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth_header}"}

    try:
        resp = requests.post(url, headers=headers, timeout=10, verify=True)
        resp.raise_for_status()
        token = resp.json().get("access_token")
        if not token:
            raise ValueError("No access_token in Zoom response")
        logger.info("Successfully obtained Zoom access token")
        return token
    except Exception as e:
        logger.error(f"Failed to get Zoom token: {str(e)}")
        raise

def zoom_api_get(endpoint):
    """Make authenticated GET request to Zoom API."""
    try:
        token = get_zoom_token(ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET)
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(f"https://api.zoom.us/v2/{endpoint}", headers=headers, timeout=30, verify=True)
        logger.info(f"Zoom API GET {endpoint}: status {resp.status_code}")

        if resp.status_code != 200:
            logger.error(f"Zoom API error {resp.status_code}: {resp.text}")
            raise RuntimeError(f"Zoom API error {resp.status_code}: {resp.text}")

        if not resp.text.strip():
            logger.error(f"Empty response from Zoom API for endpoint: {endpoint}")
            raise RuntimeError(f"Empty response from Zoom API for endpoint: {endpoint}")

        return resp.json()
    except Exception as e:
        logger.error(f"Error in zoom_api_get: {str(e)}")
        raise

@app.tool("get_zva_sessions", description="Retrieve Zoom Virtual Agent engagements within a date range and AI type")
def get_zva_sessions(
    start_date: str,
    end_date: str,
    ai_type: str = "ai_voice, ai_chat, chat",
    limit: int = 10
):
    """
    Retrieve Zoom Virtual Agent engagements within a date range.

    Args:
        start_date: Start date (e.g. "2025-12-01")
        end_date: End date (e.g. "2025-12-18")
        ai_type: AI type filter (ai_voice, ai_chat, ai_workplace)
        limit: Page size for results
    """
    logger.info(f"get_zva_sessions called: start={start_date}, end={end_date}, ai_type={ai_type}")

    endpoint = f"virtual_agent/report/engagements?from={start_date}&to={end_date}&timezone=UTC&page_size={limit}&agent_types={ai_type}"

    try:
        data = zoom_api_get(endpoint)
        engagements = data.get("engagements", [])

        engagement_info = [
            {
                "engagement_id": e.get("engagement_id"),
                "agent_type": e.get("agents", [{}])[0].get("agent_type") if e.get("agents") else None
            }
            for e in engagements
        ]

        logger.info(f"Retrieved {len(engagement_info)} engagements")

        return {
            "start_date": f"{start_date}T00:00:00Z",
            "end_date": f"{end_date}T23:59:59Z",
            "engagements": data.get("engagements", [])
        }
    except Exception as e:
        logger.error(f"Error in get_zva_sessions: {str(e)}")
        raise

@app.tool("get_zva_transcript", description="Retrieve transcript for a specific ZVA session")
def get_zva_transcript(
    engagement_ids: str,
    start_date: str,
    end_date: str,
    ai_type: str = "ai_voice",
    limit: int = 10
):
    """
    Retrieve detailed transcript for a specific ZVA engagement.

    Args:
        engagement_ids: Comma-separated engagement IDs
        start_date: Start date (e.g. "2025-12-01")
        end_date: End date (e.g. "2025-12-18")
        ai_type: AI type filter (ai_voice, ai_chat, ai_workplace)
        limit: Page size for results
    """
    logger.info(f"get_zva_transcript called: engagement_ids={engagement_ids}")

    endpoint = f"virtual_agent/report/engagements/query_details?from={start_date}T00:00:00Z&to={end_date}T23:59:59Z&timezone=UTC&page_size={limit}&agent_types={ai_type}&engagement_ids={engagement_ids}"

    try:
        data = zoom_api_get(endpoint)
        logger.info(f"Retrieved transcript details for engagement {engagement_ids}")

        return {
            "start_date": f"{start_date}T00:00:00Z",
            "end_date": f"{end_date}T23:59:59Z",
            "engagements": data.get("engagement_query_details", [])
        }
    except Exception as e:
        logger.error(f"Error in get_zva_transcript: {str(e)}")
        raise

@app.tool("analyze_zva_behavior", description="Analyze why ZVA gave a specific answer or failed")
def analyze_zva_behavior(
    engagement_ids: str,
    start_date: str,
    end_date: str,
    ai_type: str = "ai_voice",
    limit: int = 10
):
    """
    Analyze ZVA behavior by examining transcripts, variables, and query details.

    Args:
        engagement_ids: Comma-separated engagement IDs to analyze
        start_date: Start date (e.g. "2025-12-01")
        end_date: End date (e.g. "2025-12-18")
        ai_type: AI type filter (ai_voice, ai_chat, ai_workplace)
        limit: Page size for results
    """
    logger.info(f"analyze_zva_behavior called: engagement_ids={engagement_ids}")

    try:
        transcript = zoom_api_get(f"virtual_agent/report/transcripts?from={start_date}T00:00:00Z&to={end_date}T23:59:59Z&timezone=UTC&page_size={limit}&agent_types={ai_type}&engagement_ids={engagement_ids}")
        variables = zoom_api_get(f"virtual_agent/report/engagements/variables?from={start_date}T00:00:00Z&to={end_date}T23:59:59Z&timezone=UTC&page_size={limit}&agent_types={ai_type}&engagement_ids={engagement_ids}")
        details = zoom_api_get(f"virtual_agent/report/engagements/query_details?from={start_date}T00:00:00Z&to={end_date}T23:59:59Z&timezone=UTC&page_size={limit}&agent_types={ai_type}&engagement_ids={engagement_ids}")

        summary = {
            "engagement_id": engagement_ids,
            "transcript": transcript.get("transcripts", []),
            "variables": variables.get("engagement_variable_details", []),
            "details": details.get("engagement_query_details", []),
            "possible_causes": []
        }

        if not summary["variables"]:
            summary["possible_causes"].append("No variables found in transcript.")
        if summary["details"] and "fallback" in str(summary["details"]):
            summary["possible_causes"].append("Fallback intent triggered due to low confidence.")

        logger.info(f"Analysis complete for engagement {engagement_ids}")

        return summary
    except Exception as e:
        logger.error(f"Error in analyze_zva_behavior: {str(e)}")
        raise

if __name__ == "__main__":
    logger.info("Starting Zoom Virtual Agent MCP Server...")
    app.run(transport="streamable-http")
