import os, httpx, logging
from typing import Optional, Literal, Any, Dict
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

# Configure Server Settings
mcp.settings.host = "0.0.0.0"
mcp.settings.port = 8086
mcp.settings.transport_security.enable_dns_rebinding_protection = False

# --- Configuration ---
# These will now be pulled from your .env file automatically
SNOW_BASE_URL = os.environ.get("SNOW_BASE_URL", "https://ven05620.service-now.com").rstrip("/")
SNOW_CREDENTIAL = os.environ.get("SNOW_CREDENTIAL", "")  # Base64 user:pass
VA_SYS_ID = os.environ.get("VA_SYS_ID", "")  # Virtual Agent SysID

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mcp-servicenow")

async def get_headers():
    auth_header = f"Basic {SNOW_CREDENTIAL.strip()}"
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": auth_header,
    }

@mcp.tool()
async def get_userID_by_contact(phone_number: Optional[str] = None, email: Optional[str] = None) -> str:
    """
    Find a ServiceNow user's SysID and Name using their phone number or email address.
    Searches by phone first, then falls back to email if provided.
    """
    logger.info(f"Tool Called: get_userID_by_contact | Parameters: phone='{phone_number}', email='{email}'")
    headers = await get_headers()
    
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        try:
            user = None
            
            # 1. Try searching by phone if provided
            if phone_number:
                logger.info(f"Searching for user by phone: {phone_number}")
                user_query = f"phone={phone_number}^ORmobile_phone={phone_number}"
                user_url = f"{SNOW_BASE_URL}/api/now/table/sys_user"
                user_params = {"sysparm_query": user_query, "sysparm_limit": 1}
                
                resp = await client.get(user_url, headers=headers, params=user_params)
                resp.raise_for_status()
                results = resp.json().get("result", [])
                if results:
                    user = results[0]

            # 2. If no user found yet, try searching by email if provided
            if not user and email:
                logger.info(f"No user found by phone (or phone not provided). Searching by email: {email}")
                user_query = f"email={email}"
                user_url = f"{SNOW_BASE_URL}/api/now/table/sys_user"
                user_params = {"sysparm_query": user_query, "sysparm_limit": 1}
                
                resp = await client.get(user_url, headers=headers, params=user_params)
                resp.raise_for_status()
                results = resp.json().get("result", [])
                if results:
                    user = results[0]

            if not user:
                search_terms = f"phone: {phone_number}" if phone_number else ""
                if email:
                    search_terms += f", email: {email}"
                logger.warning(f"No user found for: {search_terms}")
                return f"No user found for provided contact info ({search_terms})."

            # User found
            logger.info(f"User Found: {user['name']} (ID: {user['sys_id']})")
            return f"User Found: {user['name']}\nUser SysID: {user['sys_id']}"

        except Exception as e:
            logger.error(f"Error in get_userID_by_contact: {str(e)}")
            return f"Error: {str(e)}"            

@mcp.tool()
async def get_open_incidents_by_user(user_sys_id: str) -> str:
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
async def get_open_interactions_by_user(user_sys_id: str) -> str:
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
    contact_sys_id: str, 
    short_desc: str, 
    full_desc: str, 
    issue_type: str = "inquiry",
    preferred_name: str = "Unknown"
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
    contact_sys_id: str, 
    short_desc: str, 
    full_desc: str, 
    preferred_name: str = "Unknown"
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
    incident_sys_id: str, 
    short_desc: Optional[str] = None, 
    state: str = "2", 
    work_notes: Optional[str] = None
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
    interaction_sys_id: str, 
    work_notes: str, 
    state: str = "work_in_progress"
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
async def close_incident(incident_sys_id: str, close_code: str, resolution_notes: str) -> str:    
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
    interaction_sys_id: str, 
    work_notes: str = "Interaction closed after successful resolution.",
    close_notes: str = "Resolved by Virtual Agent.",
    state: str = "closed_complete"
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