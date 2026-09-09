import os, httpx, logging, base64
from typing import Annotated, Optional, List
from pydantic import Field, BaseModel
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Find the directory where servicenow_mcp.py lives, then look for .env in the parent directory
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
env_loaded = load_dotenv(dotenv_path=env_path)

if env_loaded:
    print(f"Successfully loaded .env file from: {os.path.abspath(env_path)}")
else:
    print(f"Warning: Could not find or load .env file at: {os.path.abspath(env_path)}")

# Initialize FastMCP server
mcp = FastMCP("ServiceNow Connector")

# Response Models
class UserInfo(BaseModel):
    name: str = Field(description="ServiceNow user name")
    sys_id: str = Field(description="ServiceNow user SysID")

class UserContactResult(BaseModel):
    users: List[UserInfo] = Field(description="List of users found for the contact info")

# Configure Server Settings
mcp.settings.host = "0.0.0.0"
mcp.settings.port = 8086
mcp.settings.transport_security.enable_dns_rebinding_protection = False

# --- Configuration ---
# These will now be pulled from your .env file automatically
SNOW_BASE_URL = os.environ.get("SNOW_BASE_URL", "https://ven05620.service-now.com").rstrip("/")
#SNOW_CREDENTIAL = os.environ.get("SNOW_CREDENTIAL", "")  # Base64 user:pass
VA_SYS_ID = os.environ.get("VA_SYS_ID", "")  # Virtual Agent SysID"""

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mcp-servicenow")

# Generate auth token from email and password
def generate_auth_token(email: str, password: str) -> str:
    """Generate base64 encoded auth token from email and password."""
    credentials = f"{email}:{password}"
    return base64.b64encode(credentials.encode()).decode()

async def get_headers():
    auth_header = f"Basic {SNOW_CREDENTIAL.strip()}"
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": auth_header,
    }

@mcp.tool()
async def configure_credentials(
    email: Annotated[str, Field(description="ServiceNow user email address. Example: admin@company.service-now.com")],
    password: Annotated[str, Field(description="ServiceNow user password")]
) -> str:
    """
    Configure ServiceNow credentials using email and password.
    This generates the Base64 auth token and stores it for subsequent API calls.
    """
    global SNOW_CREDENTIAL
    try:
        SNOW_CREDENTIAL = generate_auth_token(email, password)
        logger.info(f"Credentials configured for email: {email}")
        return f"Credentials successfully configured for {email}"
    except Exception as e:
        logger.error(f"Failed to configure credentials: {str(e)}")
        return f"Error configuring credentials: {str(e)}"

@mcp.tool()
async def get_userID_by_contact(phone_number: Annotated[Optional[str],Field(description="The user's phone number, including country code. Example: +14155552671")] = None, email: Annotated[Optional[str],Field(description="The user's email address. Example: john.doe@example.com")] = None,) -> UserContactResult:
    """
    Find all ServiceNow users' SysID and Name using their phone number or email address.
    Searches by phone first, then falls back to email if provided.
    Returns all users with their name and SysID.
    """
    logger.info(f"Tool Called: get_userID_by_contact | Parameters: phone='{phone_number}', email='{email}'")
    headers = await get_headers()

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        try:
            users = []

            # 1. Try searching by phone if provided
            if phone_number:
                logger.info(f"Searching for users by phone: {phone_number}")
                user_query = f"phone={phone_number}^ORmobile_phone={phone_number}"
                user_url = f"{SNOW_BASE_URL}/api/now/table/sys_user"
                user_params = {"sysparm_query": user_query, "sysparm_fields": "name,sys_id"}

                resp = await client.get(user_url, headers=headers, params=user_params)
                resp.raise_for_status()
                results = resp.json().get("result", [])
                if results:
                    users.extend(results)

            # 2. If no users found yet, try searching by email if provided
            if not users and email:
                logger.info(f"No users found by phone (or phone not provided). Searching by email: {email}")
                user_query = f"email={email}"
                user_url = f"{SNOW_BASE_URL}/api/now/table/sys_user"
                user_params = {"sysparm_query": user_query, "sysparm_fields": "name,sys_id"}

                resp = await client.get(user_url, headers=headers, params=user_params)
                resp.raise_for_status()
                results = resp.json().get("result", [])
                if results:
                    users.extend(results)

            if not users:
                search_terms = f"phone: {phone_number}" if phone_number else ""
                if email:
                    search_terms += f", email: {email}"
                logger.warning(f"No users found for: {search_terms}")
                return UserContactResult(users=[])

            # Users found
            logger.info(f"Found {len(users)} user(s) for the provided contact info")
            user_objects = [UserInfo(name=user['name'], sys_id=user['sys_id']) for user in users]
            return UserContactResult(users=user_objects)

        except Exception as e:
            logger.error(f"Error in get_userID_by_contact: {str(e)}")
            raise Exception(f"Error: {str(e)}")            

@mcp.tool()
async def get_open_incidents_by_user(
    user_sys_id: Annotated[str, Field(description="The ServiceNow user's SysID. Example: a1b2c3d4e5f6g7h8")]
) -> str:
    """
    Fetch all open incidents (state != 7) for a specific user SysID.
    """
    logger.info(f"Tool Called: get_open_incidents_by_user | Parameters: user_sys_id='{user_sys_id}'")
    headers = await get_headers()
    
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        try:
            incident_url = f"{SNOW_BASE_URL}/api/now/table/incident"
            inc_params = {
                "sysparm_query": f"caller_id={user_sys_id}^state!=7",
                "sysparm_fields": "number,short_description,state,sys_id"
            }
            
            inc_resp = await client.get(incident_url, headers=headers, params=inc_params)
            inc_resp.raise_for_status()
            incidents_list = inc_resp.json().get("result", [])

            if not incidents_list:
                logger.info(f"No open incidents found for user: {user_sys_id}")
                return f"No open incidents were found for User ID: {user_sys_id}."

            logger.info(f"Found {len(incidents_list)} open incidents for user: {user_sys_id}")
            readable_list = "\n".join([
                f"{i['number']} - {i['short_description']} (State: {i['state']}) [SysID: {i['sys_id']}]" 
                for i in incidents_list
            ])
            
            return f"Open Incidents:\n{readable_list}"

        except Exception as e:
            logger.error(f"Error in get_open_incidents_by_user: {str(e)}")
            return f"Error: {str(e)}"

@mcp.tool()
async def get_open_interactions_by_user(
    user_sys_id: Annotated[str, Field(description="The ServiceNow user's SysID. Example: a1b2c3d4e5f6g7h8")]
) -> str:
    """
    Get interaction details for a specific user SysID (excluding closed_complete).
    """
    logger.info(f"Tool Called: get_open_interactions_by_user | Parameters: user_sys_id='{user_sys_id}'")
    headers = await get_headers()
    
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        try:
            url = f"{SNOW_BASE_URL}/api/now/table/interaction"
            params = {
                "sysparm_query": f"opened_for={user_sys_id}^state!=closed_complete",
                "sysparm_fields": "number,short_description,state,sys_id,contact,sys_created_by,sys_updated_by"
            }
            
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            interactions = resp.json().get("result", [])
            
            if not interactions:
                logger.info(f"No open interactions for user: {user_sys_id}")
                return f"No open interactions found for User SysID: {user_sys_id}"
            
            logger.info(f"Found {len(interactions)} open interactions for user: {user_sys_id}")
            readable_list = "\n".join([
                f"{i['number']} - {i.get('short_description', 'No description')} (State: {i['state']}) [SysID: {i['sys_id']}]"
                for i in interactions
            ])
            
            return f"Open Interactions for User {user_sys_id}:\n{readable_list}"
            
        except Exception as e:
            logger.error(f"Error in get_user_interactions: {str(e)}")
            return f"Error: {str(e)}"

@mcp.tool()
async def create_incident(
    contact_sys_id: Annotated[str, Field(description="The ServiceNow user/contact SysID. Example: a1b2c3d4e5f6g7h8")],
    short_desc: Annotated[str, Field(description="Brief incident summary. Example: Password reset request")],
    full_desc: Annotated[str, Field(description="Detailed incident description with all relevant information")],
    issue_type: Annotated[str, Field(description="Incident category/issue type. Example: inquiry, question, problem")] = "inquiry",
    preferred_name: Annotated[str, Field(description="Contact's preferred name for the incident. Example: John Doe")] = "Unknown"
) -> str:
    """
    Create a new Incident in ServiceNow.
    """
    logger.info(f"Tool Called: create_incident | Parameters: caller='{preferred_name}', category='{issue_type}', contact_sys_id='{contact_sys_id}'")
    headers = await get_headers()
    payload = {
        "category": issue_type,
        "contact_type": "virtual_agent",
        "assigned_to": VA_SYS_ID,
        "description": f"Inbound Contact Center Call from: {preferred_name} with the issue selected as: {issue_type}. {full_desc}",
        "short_description": short_desc,
        "state": "1",
        "caller_id": contact_sys_id
    }

    async with httpx.AsyncClient(verify=False) as client:
        try:
            url = f"{SNOW_BASE_URL}/api/now/table/incident?sysparm_fields=sys_id,number"
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            result = resp.json().get("result", {})
            logger.info(f"Successfully created Incident: {result.get('number')}")
            return f"Incident Created: {result.get('number')} (SysID: {result.get('sys_id')})"
        except Exception as e:
            logger.error(f"Failed to create incident: {str(e)}")
            return f"Error creating incident: {str(e)}"

@mcp.tool()
async def create_interaction(
    contact_sys_id: Annotated[str, Field(description="The ServiceNow user/contact SysID. Example: a1b2c3d4e5f6g7h8")],
    short_desc: Annotated[str, Field(description="Brief interaction summary. Example: Account inquiry call")],
    full_desc: Annotated[str, Field(description="Detailed interaction description with call notes and details")],
    preferred_name: Annotated[str, Field(description="Contact's preferred name. Example: Jane Smith")] = "Unknown"
) -> str:
    """
    Create a new Interaction record.
    """
    logger.info(f"Tool Called: create_interaction | Parameters: caller='{preferred_name}', contact_sys_id='{contact_sys_id}'")
    headers = await get_headers()
    payload = {
        "short_description": f"{short_desc} - captured by Virtual Agent",
        "description": f"Caller: {preferred_name} | Channel: phone | Captured by VA {full_desc}",
        "work_notes": f"Caller: {preferred_name} | Channel: phone | Captured by VA {full_desc}",
        "type": "Phone",
        "contact": contact_sys_id,
        "opened_for": contact_sys_id
    }

    async with httpx.AsyncClient(verify=False) as client:
        try:
            url = f"{SNOW_BASE_URL}/api/now/table/interaction?sysparm_fields=sys_id,number"
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            result = resp.json().get("result", {})
            logger.info(f"Successfully created Interaction: {result.get('number')}")
            return f"Interaction Created: {result.get('number')} (SysID: {result.get('sys_id')})"
        except Exception as e:
            logger.error(f"Failed to create interaction: {str(e)}")
            return f"Error creating interaction: {str(e)}"

@mcp.tool()
async def update_incident(
    incident_sys_id: Annotated[str, Field(description="The ServiceNow incident SysID. Example: a1b2c3d4e5f6g7h8")],
    short_desc: Annotated[Optional[str], Field(description="Updated incident summary. Example: Updated: Password reset completed")] = None,
    state: Annotated[str, Field(description="Incident state code. 1=New, 2=In Progress, 3=On Hold, 4=Resolved, 7=Closed. Default: 2")] = "2",
    work_notes: Annotated[Optional[str], Field(description="Internal work notes or updates to the incident")] = None
) -> str:
    """
    Update an existing Incident. Default state is '2' (In Progress).
    """
    logger.info(f"Tool Called: update_incident | Parameters: incident_sys_id='{incident_sys_id}', state='{state}'")
    headers = await get_headers()
    payload = {
        #"assigned_to": VA_SYS_ID,
        "short_description": short_desc,
        "state": state
    }
    
    if state == "3":
        payload["hold_reason"] = "2"
    
    if work_notes:
        payload["work_notes"] = work_notes
    
    async with httpx.AsyncClient(verify=False) as client:
        try:
            url = f"{SNOW_BASE_URL}/api/now/table/incident/{incident_sys_id}"
            resp = await client.put(url, headers=headers, json=payload)
            resp.raise_for_status()
            logger.info(f"Successfully updated Incident {incident_sys_id} to state {state}")
            return f"Incident {incident_sys_id} updated successfully to state {state}. Status: {resp.status_code}"
        except Exception as e:
            logger.error(f"Failed to update incident {incident_sys_id}: {str(e)}")
            return f"Error updating incident: {str(e)}"

@mcp.tool()
async def update_interaction(
    interaction_sys_id: Annotated[str, Field(description="The ServiceNow interaction SysID. Example: a1b2c3d4e5f6g7h8")],
    work_notes: Annotated[str, Field(description="Work notes or updates to the interaction")],
    state: Annotated[str, Field(description="Interaction state. Example: work_in_progress, resolved, closed_complete. Default: work_in_progress")] = "work_in_progress"
) -> str:
    """
    Update an existing Interaction (Default state: work_in_progress).
    """
    logger.info(f"Tool Called: update_interaction | Parameters: interaction_sys_id='{interaction_sys_id}', state='{state}'")
    headers = await get_headers()
    payload = {
        "work_notes": work_notes,
        "state": state,
        "assigned_to": VA_SYS_ID
    }
    
    async with httpx.AsyncClient(verify=False) as client:
        try:
            url = f"{SNOW_BASE_URL}/api/now/table/interaction/{interaction_sys_id}"
            resp = await client.patch(url, headers=headers, json=payload)
            resp.raise_for_status()
            logger.info(f"Successfully updated Interaction {interaction_sys_id} to {state}")
            return f"Interaction {interaction_sys_id} updated to {state}. Status: {resp.status_code}"
        except Exception as e:
            logger.error(f"Failed to update interaction {interaction_sys_id}: {str(e)}")
            return f"Error updating interaction: {str(e)}"

@mcp.tool()
async def close_incident(
    incident_sys_id: Annotated[str, Field(description="The ServiceNow incident SysID. Example: a1b2c3d4e5f6g7h8")],
    close_code: Annotated[str, Field(description="Incident closure reason code. Example: resolved, cancelled, duplicate")],
    resolution_notes: Annotated[str, Field(description="Summary of how the incident was resolved")]
) -> str:
    """
    Close an Incident.
    """
    logger.info(f"Tool Called: close_incident | Parameters: incident_sys_id='{incident_sys_id}', close_code='{close_code}'")
    headers = await get_headers()
    payload = {
        #"short_description": "The inbound call has been completed by the virtual agent",
        "state": "7",
        "close_code": close_code,
        "close_notes": f"Resolved successfully by Virtual Agent. {resolution_notes}"
    }

    async with httpx.AsyncClient(verify=False) as client:
        try:
            url = f"{SNOW_BASE_URL}/api/now/table/incident/{incident_sys_id}"
            resp = await client.patch(url, headers=headers, json=payload)
            resp.raise_for_status()
            logger.info(f"Successfully closed Incident {incident_sys_id}")
            return f"Incident {incident_sys_id} closed successfully."
        except Exception as e:
            logger.error(f"Failed to close incident {incident_sys_id}: {str(e)}")
            return f"Error closing incident: {str(e)}"

@mcp.tool()
async def close_interaction(
    interaction_sys_id: Annotated[str, Field(description="The ServiceNow interaction SysID. Example: a1b2c3d4e5f6g7h8")],
    work_notes: Annotated[str, Field(description="Final work notes on the interaction")] = "Interaction closed after successful resolution.",
    close_notes: Annotated[str, Field(description="Closure notes summarizing the resolution")] = "Resolved by Virtual Agent.",
    state: Annotated[str, Field(description="Final interaction state. Default: closed_complete")] = "closed_complete"
) -> str:
    """
    Close an Interaction with notes.
    """
    logger.info(f"Tool Called: close_interaction | Parameters: interaction_sys_id='{interaction_sys_id}', state='{state}'")
    headers = await get_headers()
    payload = {
        "state": state,
        "work_notes": work_notes,
        "close_notes": close_notes
    }
    
    async with httpx.AsyncClient(verify=False) as client:
        try:
            url = f"{SNOW_BASE_URL}/api/now/table/interaction/{interaction_sys_id}"
            resp = await client.patch(url, headers=headers, json=payload)
            resp.raise_for_status()
            logger.info(f"Successfully closed Interaction {interaction_sys_id}")
            return f"Interaction {interaction_sys_id} closed successfully."
        except Exception as e:
            logger.error(f"Failed to close interaction {interaction_sys_id}: {str(e)}")
            return f"Error closing interaction: {str(e)}"

if __name__ == "__main__":
    # To run: python servicenow_mcp.py
    mcp.run(transport="streamable-http")