# mcp_server.py
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import httpx, base64, os, logging

app = FastMCP("ZVA MCP server")

app.settings.host = "0.0.0.0"
app.settings.port = 8089
app.settings.transport_security.enable_dns_rebinding_protection = False

# Setup logging (minimal at module load)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mcp-zva")

# Load environment variables once at startup
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# Consolidated credential loading (cached for performance)
ACCOUNT_ID = os.getenv("ZOOM_ACCOUNT_ID", "").strip().strip("'\"")
CLIENT_ID = os.getenv("ZOOM_CLIENT_ID", "").strip().strip("'\"")
CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET", "").strip().strip("'\"")

# Track if startup logging has been done (lazy initialization)
_startup_logged = False

def _log_startup_once():
    """Log startup configuration on first tool call (lazy initialization)."""
    global _startup_logged
    if _startup_logged:
        return
    _startup_logged = True
    logger.info("=" * 50)
    logger.info("Zoom Virtual Agent MCP Server initialized")
    logger.info(f"Credentials configured: {bool(ACCOUNT_ID and CLIENT_ID and CLIENT_SECRET)}")
    logger.info("=" * 50)


async def get_zoom_token(account_id: str, client_id: str, client_secret: str):
    """Generate a Zoom OAuth token using account credentials."""
    url = f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={account_id}"
    auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth_header}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers)
        resp.raise_for_status()
        return resp.json()["access_token"]


async def zoom_api_get(endpoint: str, account_id: str, client_id: str, client_secret: str):
    """Make an authenticated GET request to the Zoom API."""
    token = await get_zoom_token(account_id, client_id, client_secret)
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"https://api.zoom.us/v2/{endpoint}", headers=headers)
        logger.info(f"Zoom API Status: {resp.status_code}")

        if resp.status_code != 200:
            raise RuntimeError(f"Zoom API error {resp.status_code}: {resp.text}")

        if not resp.text.strip():
            raise RuntimeError(f"Empty response from Zoom API for endpoint: {endpoint}")

        return resp.json()


@app.tool()
async def configure_zoom_credentials(account_id: str, client_id: str, client_secret: str):
    """
    Configure Zoom credentials for API access by validating them with a token generation test.

    Args:
        account_id: Zoom Account ID
        client_id: Zoom Client ID
        client_secret: Zoom Client Secret
    """
    global ACCOUNT_ID, CLIENT_ID, CLIENT_SECRET
    _log_startup_once()
    try:
        # Validate credentials by generating a token
        token = await get_zoom_token(account_id, client_id, client_secret)

        # Store credentials for subsequent tool calls
        ACCOUNT_ID = account_id
        CLIENT_ID = client_id
        CLIENT_SECRET = client_secret

        logger.info(f"Zoom credentials configured successfully for Account ID: {account_id}")
        return f"Zoom credentials successfully configured for Account ID: {account_id}"
    except Exception as e:
        logger.error(f"Failed to configure Zoom credentials: {str(e)}")
        return f"Error configuring credentials: {str(e)}"


@app.tool()
async def get_contact_center_history(
    phone_number: str,
    from_date: str = None,
    to_date: str = None
):
    """
    Retrieve engagement history from Zoom Contact Center (29-day default window).

    Args:
        phone_number: Phone number to query (e.g., "+1234567890")
        from_date: Start date YYYY-MM-DD (defaults to 29 days ago)
        to_date: End date YYYY-MM-DD (defaults to today)
    """
    _log_startup_once()
    logger.info(f"Tool Called: get_contact_center_history | Parameters: phone='{phone_number}'")

    if not ACCOUNT_ID or not CLIENT_ID or not CLIENT_SECRET:
        return {"status": "Error", "detail": "Zoom credentials not configured. Call configure_zoom_credentials first."}

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
        # --- 4. AUTHENTICATION & API CALL ---
        api_url = 'https://api.zoom.us/v2/contact_center/engagements'
        final_url = f"{api_url}?from={from_date}&to={to_date}&consumer_number={encoded_phone}&page_size=100"
        logger.info(f"Final URL: {final_url}")

        token = await get_zoom_token(ACCOUNT_ID, CLIENT_ID, CLIENT_SECRET)
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(final_url, headers=headers)

        if response.status_code != 200:
            return {"status": "Error", "code": response.status_code, "detail": response.text}

        data = response.json()
        logger.info(f"API Response: {data}")

        if not data.get("engagements") or len(data.get("engagements", [])) == 0:
            return {"status": "No History", "engagement_count": 0}

        # --- 5. PARSE DATA ---
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
        logger.error(f"Error in get_contact_center_history: {str(err)}")
        return {"status": "Error", "detail": str(err)}


@app.tool()
async def get_zva_sessions(
    start_date: str,
    end_date: str,
    ai_type: str = "ai_voice, ai_chat, chat",
    limit: int = 10
):
    """
    Retrieve Zoom Virtual Agent engagements within a date range.

    Args:
        start_date: Start date YYYY-MM-DD (e.g., "2025-12-01")
        end_date: End date YYYY-MM-DD (e.g., "2025-12-18")
        ai_type: Agent types (default: "ai_voice, ai_chat, chat")
        limit: Max records to return (default: 10)
    """
    _log_startup_once()
    logger.info(f"Tool Called: get_zva_sessions | Parameters: start_date='{start_date}', end_date='{end_date}'")

    if not ACCOUNT_ID or not CLIENT_ID or not CLIENT_SECRET:
        return {"status": "Error", "detail": "Zoom credentials not configured. Call configure_zoom_credentials first."}

    try:
        endpoint = f"virtual_agent/report/engagements?from={start_date}&to={end_date}&timezone=UTC&page_size={limit}&agent_types={ai_type}"
        logger.info(f"Endpoint: {endpoint}")

        data = await zoom_api_get(endpoint, ACCOUNT_ID, CLIENT_ID, CLIENT_SECRET)
        engagements = data.get("engagements", [])

        engagement_info = [
            {
                "engagement_id": e.get("engagement_id"),
                "agent_type": e.get("agents", [{}])[0].get("agent_type") if e.get("agents") else None
            }
            for e in engagements
        ]

        logger.info(f"Engagements (ID and Agent Type): {engagement_info}")

        return {
            "start_date": f"{start_date}T00:00:00Z",
            "end_date": f"{end_date}T23:59:59Z",
            "engagements": data.get("engagements", [])
        }

    except Exception as e:
        logger.error(f"Error in get_zva_sessions: {str(e)}")
        return {"status": "Error", "detail": str(e)}


@app.tool()
async def get_zva_transcript(
    engagement_ids: str,
    start_date: str,
    end_date: str,
    ai_type: str = "ai_voice",
    limit: int = 10
):
    """
    Retrieve transcript for specific ZVA session(s) within a date range.

    Args:
        engagement_ids: Comma-separated engagement IDs
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        ai_type: Agent type (default: "ai_voice")
        limit: Max records to return (default: 10)
    """
    _log_startup_once()
    logger.info(f"Tool Called: get_zva_transcript | Parameters: engagement_ids='{engagement_ids}'")

    if not ACCOUNT_ID or not CLIENT_ID or not CLIENT_SECRET:
        return {"status": "Error", "detail": "Zoom credentials not configured. Call configure_zoom_credentials first."}

    try:
        endpoint = f"virtual_agent/report/engagements/query_details?from={start_date}T00:00:00Z&to={end_date}T23:59:59Z&timezone=UTC&page_size={limit}&agent_types={ai_type}&engagement_ids={engagement_ids}"
        data = await zoom_api_get(endpoint, ACCOUNT_ID, CLIENT_ID, CLIENT_SECRET)

        return {
            "start_date": f"{start_date}T00:00:00Z",
            "end_date": f"{end_date}T23:59:59Z",
            "engagements": data.get("engagement_query_details", [])
        }

    except Exception as e:
        logger.error(f"Error in get_zva_transcript: {str(e)}")
        return {"status": "Error", "detail": str(e)}


@app.tool()
async def analyze_zva_behavior(
    engagement_ids: str,
    start_date: str,
    end_date: str,
    ai_type: str = "ai_voice",
    limit: int = 10
):
    """
    Analyze why ZVA gave specific answers or failed in engagement(s).

    Args:
        engagement_ids: Comma-separated engagement IDs
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        ai_type: Agent type (default: "ai_voice")
        limit: Max records to return (default: 10)
    """
    _log_startup_once()
    logger.info(f"Tool Called: analyze_zva_behavior | Parameters: engagement_ids='{engagement_ids}'")

    if not ACCOUNT_ID or not CLIENT_ID or not CLIENT_SECRET:
        return {"status": "Error", "detail": "Zoom credentials not configured. Call configure_zoom_credentials first."}

    try:
        transcript = await zoom_api_get(
            f"virtual_agent/report/transcripts?from={start_date}T00:00:00Z&to={end_date}T23:59:59Z&timezone=UTC&page_size={limit}&agent_types={ai_type}&engagement_ids={engagement_ids}",
            ACCOUNT_ID, CLIENT_ID, CLIENT_SECRET
        )
        variables = await zoom_api_get(
            f"virtual_agent/report/engagements/variables?from={start_date}T00:00:00Z&to={end_date}T23:59:59Z&timezone=UTC&page_size={limit}&agent_types={ai_type}&engagement_ids={engagement_ids}",
            ACCOUNT_ID, CLIENT_ID, CLIENT_SECRET
        )
        details = await zoom_api_get(
            f"virtual_agent/report/engagements/query_details?from={start_date}T00:00:00Z&to={end_date}T23:59:59Z&timezone=UTC&page_size={limit}&agent_types={ai_type}&engagement_ids={engagement_ids}",
            ACCOUNT_ID, CLIENT_ID, CLIENT_SECRET
        )

        logger.info(f"Transcript: {transcript}")
        logger.info(f"Variables: {variables}")
        logger.info(f"Details: {details}")

        summary = {
            "engagement_id": engagement_ids,
            "transcript": transcript.get("transcripts", []),
            "variables": variables.get("engagement_variable_details", []),
            "details": details.get("engagement_query_details", []),
            "possible_causes": []
        }

        if not summary["variables"]:
            summary["possible_causes"].append("No variables found in transcript.")
        if "fallback" in str(summary["details"]):
            summary["possible_causes"].append("Fallback intent triggered due to low confidence.")

        return summary

    except Exception as e:
        logger.error(f"Error in analyze_zva_behavior: {str(e)}")
        return {"status": "Error", "detail": str(e)}


if __name__ == "__main__":
    logger.info("Starting Zoom Virtual Agent MCP Server")
    logger.info(f"Transport: Streamable HTTP | Protocol: 2025-11-25 | Port: {app.settings.port}")
    app.run(transport="streamable-http")
