import os, httpx, logging
from typing import Annotated, Optional, List
from pydantic import Field, BaseModel
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Find the directory where sfdc_mcp.py lives, then look for .env in the parent directory
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
env_loaded = load_dotenv(dotenv_path=env_path)

if env_loaded:
    print(f"Successfully loaded .env file from: {os.path.abspath(env_path)}")
else:
    print(f"Warning: Could not find or load .env file at: {os.path.abspath(env_path)}")

# Initialize FastMCP server
mcp = FastMCP("Salesforce Connector")

# Configure Server Settings
mcp.settings.host = "0.0.0.0"
mcp.settings.port = 8090
mcp.settings.transport_security.enable_dns_rebinding_protection = False

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mcp-salesforce")

# --- Configuration ---
# Defaults can be provided via .env; configure_credentials() overrides them at runtime.
SFDC_CONFIG = {
    "base_url": os.environ.get("SFDC_BASE_URL", "").rstrip("/"),
    "api_version": os.environ.get("SFDC_API_VERSION", "v64.0"),
    "client_id": os.environ.get("SFDC_CLIENT_ID", ""),
    "client_secret": os.environ.get("SFDC_CLIENT_SECRET", ""),
    "access_token": None,
}

# Response Models
class CaseInfo(BaseModel):
    case_number: str = Field(description="Salesforce Case Number")
    case_id: Optional[str] = Field(default=None, description="Salesforce Case Id")
    subject: Optional[str] = Field(default=None, description="Case subject")
    status: Optional[str] = Field(default=None, description="Case status")
    priority: Optional[str] = Field(default=None, description="Case priority")
    description: Optional[str] = Field(default=None, description="Case description")
    owner_name: Optional[str] = Field(default=None, description="Case owner name")
    owner_email: Optional[str] = Field(default=None, description="Case owner email")
    contact_id: Optional[str] = Field(default=None, description="Related Contact Id")
    contact_email: Optional[str] = Field(default=None, description="Related Contact email")

class CaseLookupResult(BaseModel):
    count: int = Field(description="Number of cases found")
    cases: List[CaseInfo] = Field(default_factory=list, description="Matching cases")

class ContactLookupResult(BaseModel):
    found: bool = Field(description="Whether a Contact or Lead was found")
    record_type: Optional[str] = Field(default=None, description="'Contact' or 'Lead'")
    record_id: Optional[str] = Field(default=None, description="Salesforce record Id")
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    account_name: Optional[str] = Field(default=None, description="Related Account name (Contacts only)")
    open_cases: List[CaseInfo] = Field(default_factory=list, description="Open cases for this Contact")
    message: Optional[str] = Field(default=None, description="Status or error message")

# --- Helpers ---

def escape_sosl(value: str) -> str:
    """Escape SOSL reserved characters in a search term."""
    reserved = ['\\', '?', '&', '|', '!', '{', '}', '[', ']', '(', ')', '^', '~', '*', ':', '"', "'", '+', '-']
    for ch in reserved:
        value = value.replace(ch, '\\' + ch)
    return value

def escape_soql(value: str) -> str:
    """Escape a string literal for safe interpolation into a SOQL query."""
    return value.replace('\\', '\\\\').replace("'", "\\'")

async def get_access_token(force_refresh: bool = False) -> str:
    if SFDC_CONFIG["access_token"] and not force_refresh:
        return SFDC_CONFIG["access_token"]

    if not SFDC_CONFIG["base_url"] or not SFDC_CONFIG["client_id"] or not SFDC_CONFIG["client_secret"]:
        raise Exception("Salesforce credentials are not configured. Call configure_credentials first.")

    token_url = f"{SFDC_CONFIG['base_url']}/services/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": SFDC_CONFIG["client_id"],
        "client_secret": SFDC_CONFIG["client_secret"],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )
        resp.raise_for_status()
        token = resp.json().get("access_token")
        if not token:
            raise Exception("Salesforce did not return an access token.")
        SFDC_CONFIG["access_token"] = token
        return token

async def get_headers(force_refresh: bool = False) -> dict:
    token = await get_access_token(force_refresh=force_refresh)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

async def sfdc_request(method: str, path: str, **kwargs) -> httpx.Response:
    """Issue an authenticated Salesforce REST API request, refreshing the token once on a 401."""
    url = f"{SFDC_CONFIG['base_url']}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = await get_headers()
        resp = await client.request(method, url, headers=headers, **kwargs)
        if resp.status_code == 401:
            logger.info("Salesforce access token expired or invalid, refreshing...")
            headers = await get_headers(force_refresh=True)
            resp = await client.request(method, url, headers=headers, **kwargs)
        return resp

# --- Tools ---

@mcp.tool()
async def configure_credentials(
    base_url: Annotated[str, Field(description="Salesforce instance base URL. Example: https://yourorg.my.salesforce.com")],
    client_id: Annotated[str, Field(description="Connected App Consumer Key (Client ID)")],
    client_secret: Annotated[str, Field(description="Connected App Consumer Secret (Client Secret)")],
    api_version: Annotated[str, Field(description="Salesforce REST API version. Example: v64.0")] = "v64.0",
) -> str:
    """
    Configure Salesforce credentials and authenticate using the OAuth2 Client Credentials flow.
    Must be called before any other Salesforce tool.
    """
    logger.info(f"Tool Called: configure_credentials | base_url='{base_url}'")
    SFDC_CONFIG["base_url"] = base_url.rstrip("/")
    SFDC_CONFIG["client_id"] = client_id
    SFDC_CONFIG["client_secret"] = client_secret
    SFDC_CONFIG["api_version"] = api_version
    SFDC_CONFIG["access_token"] = None

    try:
        await get_access_token(force_refresh=True)
        logger.info("Salesforce credentials configured and authenticated successfully.")
        return f"Salesforce credentials successfully configured and authenticated for {SFDC_CONFIG['base_url']}"
    except Exception as e:
        logger.error(f"Failed to configure Salesforce credentials: {str(e)}")
        return f"Error configuring credentials: {str(e)}"

@mcp.tool()
async def get_contact_by_phone_or_email(
    phone_number: Annotated[Optional[str], Field(description="Caller's phone number, including country code. Example: +14155552671")] = None,
    email: Annotated[Optional[str], Field(description="Caller's email address. Example: john.doe@example.com")] = None,
) -> ContactLookupResult:
    """
    Look up a Salesforce Contact or Lead by phone number or email using SOSL.
    Searches by phone first, then falls back to email. If a Contact is found,
    also returns their open Cases.
    """
    logger.info(f"Tool Called: get_contact_by_phone_or_email | phone='{phone_number}', email='{email}'")

    if phone_number:
        search_value = escape_sosl(phone_number.lstrip("+"))
        scope = "IN PHONE FIELDS"
    elif email:
        search_value = escape_sosl(email)
        scope = "IN EMAIL FIELDS"
    else:
        return ContactLookupResult(found=False, message="No phone number or email provided.")

    sosl = (
        f"FIND {{{search_value}}} {scope} RETURNING "
        f"Contact(Id, FirstName, LastName, Email, Phone, MobilePhone, AccountId, Account.Name), "
        f"Lead(Id, FirstName, LastName, Email, Phone, MobilePhone, Company, Status)"
    )

    try:
        resp = await sfdc_request(
            "GET",
            f"/services/data/{SFDC_CONFIG['api_version']}/search/",
            params={"q": sosl},
        )
        resp.raise_for_status()
        records = resp.json().get("searchRecords", [])

        if not records:
            logger.info("No Contact or Lead found for this identifier.")
            return ContactLookupResult(found=False, message="No Contact or Lead found for this identifier.")

        match = records[0]
        is_contact = match.get("attributes", {}).get("type") == "Contact"
        record_type = "Contact" if is_contact else "Lead"
        account_name = (match.get("Account") or {}).get("Name") if is_contact else None

        result = ContactLookupResult(
            found=True,
            record_type=record_type,
            record_id=match.get("Id"),
            first_name=match.get("FirstName"),
            last_name=match.get("LastName"),
            email=match.get("Email"),
            phone=match.get("Phone") or match.get("MobilePhone"),
            account_name=account_name,
        )

        if is_contact:
            case_resp = await sfdc_request(
                "GET",
                f"/services/data/{SFDC_CONFIG['api_version']}/query",
                params={"q": f"SELECT Id, CaseNumber, Subject, Status FROM Case WHERE ContactId = '{match['Id']}' AND IsClosed = false"},
            )
            case_resp.raise_for_status()
            cases = case_resp.json().get("records", [])
            result.open_cases = [
                CaseInfo(case_number=c["CaseNumber"], case_id=c.get("Id"), subject=c.get("Subject"), status=c.get("Status"))
                for c in cases
            ]
            logger.info(f"Found {record_type} {match['Id']} with {len(cases)} open case(s).")
        else:
            logger.info(f"Found {record_type} {match['Id']}.")

        return result

    except Exception as e:
        logger.error(f"Error in get_contact_by_phone_or_email: {str(e)}")
        return ContactLookupResult(found=False, message=f"Error: {str(e)}")

@mcp.tool()
async def lookup_cases(
    case_number: Annotated[Optional[str], Field(description="Salesforce case number to look up. Example: 00001234")] = None,
    contact_id: Annotated[Optional[str], Field(description="Salesforce Contact Id to list cases for. Example: 003XXXXXXXXXXXXAAA")] = None,
    include_closed: Annotated[bool, Field(description="When searching by contact_id, whether to include closed cases. Default: false")] = False,
    limit: Annotated[int, Field(description="Maximum number of cases to return. Default: 10")] = 10,
) -> CaseLookupResult:
    """
    Look up Salesforce Cases either by case number or by the Contact who filed them.
    """
    logger.info(f"Tool Called: lookup_cases | case_number='{case_number}', contact_id='{contact_id}'")

    fields = "Id, CaseNumber, Subject, Status, Priority, Description, Owner.Name, Owner.Email, ContactId, Contact.Email"

    if case_number:
        query = f"SELECT {fields} FROM Case WHERE CaseNumber = '{escape_soql(case_number)}' LIMIT {limit}"
    elif contact_id:
        query = f"SELECT {fields} FROM Case WHERE ContactId = '{escape_soql(contact_id)}'"
        if not include_closed:
            query += " AND IsClosed = false"
        query += f" LIMIT {limit}"
    else:
        logger.warning("lookup_cases called without case_number or contact_id.")
        return CaseLookupResult(count=0, cases=[])

    try:
        resp = await sfdc_request(
            "GET",
            f"/services/data/{SFDC_CONFIG['api_version']}/query",
            params={"q": query},
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])

        cases = [
            CaseInfo(
                case_number=c["CaseNumber"],
                case_id=c.get("Id"),
                subject=c.get("Subject"),
                status=c.get("Status"),
                priority=c.get("Priority"),
                description=c.get("Description"),
                owner_name=(c.get("Owner") or {}).get("Name"),
                owner_email=(c.get("Owner") or {}).get("Email"),
                contact_id=c.get("ContactId"),
                contact_email=(c.get("Contact") or {}).get("Email"),
            )
            for c in records
        ]

        logger.info(f"Found {len(cases)} case(s).")
        return CaseLookupResult(count=len(cases), cases=cases)

    except Exception as e:
        logger.error(f"Error in lookup_cases: {str(e)}")
        return CaseLookupResult(count=0, cases=[])

@mcp.tool()
async def create_case(
    contact_id: Annotated[str, Field(description="Salesforce Contact Id to associate with the case. Example: 003XXXXXXXXXXXXAAA")],
    subject: Annotated[str, Field(description="Brief case summary. Example: Unable to access account")],
    description: Annotated[str, Field(description="Detailed description of the issue")],
    priority: Annotated[str, Field(description="Case priority. Example: Low, Medium, High. Default: Medium")] = "Medium",
    origin: Annotated[str, Field(description="Case origin. Example: Phone, Email, Web. Default: Phone")] = "Phone",
    status: Annotated[str, Field(description="Initial case status. Default: New")] = "New",
) -> str:
    """
    Create a new Salesforce Case for a Contact.
    """
    logger.info(f"Tool Called: create_case | contact_id='{contact_id}', subject='{subject}'")
    payload = {
        "ContactId": contact_id,
        "Subject": subject,
        "Description": description,
        "Priority": priority,
        "Origin": origin,
        "Status": status,
    }

    try:
        resp = await sfdc_request(
            "POST",
            f"/services/data/{SFDC_CONFIG['api_version']}/sobjects/Case",
            json=payload,
        )
        if resp.status_code != 201:
            raise Exception(f"{resp.status_code} - {resp.text}")

        result = resp.json()
        case_id = result.get("id")

        # Fetch the auto-generated CaseNumber for a human-readable reference
        case_number = None
        lookup = await sfdc_request(
            "GET",
            f"/services/data/{SFDC_CONFIG['api_version']}/sobjects/Case/{case_id}",
            params={"fields": "CaseNumber"},
        )
        if lookup.status_code == 200:
            case_number = lookup.json().get("CaseNumber")

        logger.info(f"Successfully created Case {case_number or case_id}")
        return f"Case created successfully. Case Number: {case_number}, Case Id: {case_id}"

    except Exception as e:
        logger.error(f"Failed to create case: {str(e)}")
        return f"Error creating case: {str(e)}"

@mcp.tool()
async def update_case(
    case_id: Annotated[str, Field(description="Salesforce Case Id to update. Example: 500XXXXXXXXXXXXAAA")],
    subject: Annotated[Optional[str], Field(description="Updated case subject")] = None,
    description: Annotated[Optional[str], Field(description="Updated case description")] = None,
    priority: Annotated[Optional[str], Field(description="Updated case priority. Example: Low, Medium, High")] = None,
    status: Annotated[Optional[str], Field(description="Updated case status. Example: New, Working, Escalated")] = None,
) -> str:
    """
    Update fields on an existing Salesforce Case. Only the fields provided are changed.
    """
    logger.info(f"Tool Called: update_case | case_id='{case_id}'")
    payload = {}
    if subject is not None:
        payload["Subject"] = subject
    if description is not None:
        payload["Description"] = description
    if priority is not None:
        payload["Priority"] = priority
    if status is not None:
        payload["Status"] = status

    if not payload:
        return "No fields provided to update."

    try:
        resp = await sfdc_request(
            "PATCH",
            f"/services/data/{SFDC_CONFIG['api_version']}/sobjects/Case/{case_id}",
            json=payload,
        )
        if resp.status_code != 204:
            raise Exception(f"{resp.status_code} - {resp.text}")

        logger.info(f"Successfully updated Case {case_id}")
        return f"Case {case_id} updated successfully."

    except Exception as e:
        logger.error(f"Failed to update case {case_id}: {str(e)}")
        return f"Error updating case: {str(e)}"

@mcp.tool()
async def close_case(
    case_id: Annotated[str, Field(description="Salesforce Case Id to close. Example: 500XXXXXXXXXXXXAAA")],
    resolution_notes: Annotated[str, Field(description="Summary of how the case was resolved")],
    status: Annotated[str, Field(description="Closed status value used by your org. Default: Closed")] = "Closed",
) -> str:
    """
    Close a Salesforce Case, appending resolution notes to its description.
    """
    logger.info(f"Tool Called: close_case | case_id='{case_id}'")

    try:
        existing_description = ""
        get_resp = await sfdc_request(
            "GET",
            f"/services/data/{SFDC_CONFIG['api_version']}/sobjects/Case/{case_id}",
            params={"fields": "Description"},
        )
        if get_resp.status_code == 200:
            existing_description = get_resp.json().get("Description") or ""

        payload = {
            "Status": status,
            "Description": f"{existing_description}\n\n[Case Closed] {resolution_notes}".strip(),
        }

        resp = await sfdc_request(
            "PATCH",
            f"/services/data/{SFDC_CONFIG['api_version']}/sobjects/Case/{case_id}",
            json=payload,
        )
        if resp.status_code != 204:
            raise Exception(f"{resp.status_code} - {resp.text}")

        logger.info(f"Successfully closed Case {case_id}")
        return f"Case {case_id} closed successfully."

    except Exception as e:
        logger.error(f"Failed to close case {case_id}: {str(e)}")
        return f"Error closing case: {str(e)}"

if __name__ == "__main__":
    # To run: python sfdc_mcp.py
    mcp.run(transport="streamable-http")
