"""
Auth helpers for Azure SWA.

SWA injects two headers into every API request:
  X-MS-CLIENT-PRINCIPAL      base64-encoded JSON with claims
  X-MS-CLIENT-PRINCIPAL-NAME the user's identity (email for AAD)

We decode these to get the logged-in user's email, then check Mercury
for director/finance-team membership to determine admin status.
"""
import base64, json, logging
import azure.functions as func


def get_user_email(req: func.HttpRequest) -> str | None:
    """Returns the authenticated user's email, or None if not authenticated."""
    name = req.headers.get("X-MS-CLIENT-PRINCIPAL-NAME")
    if name:
        return name

    # Fallback: decode the principal blob
    principal_b64 = req.headers.get("X-MS-CLIENT-PRINCIPAL")
    if not principal_b64:
        return None
    try:
        principal = json.loads(base64.b64decode(principal_b64 + "==").decode("utf-8"))
        claims = {c["typ"]: c["val"] for c in principal.get("claims", [])}
        return (
            claims.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress")
            or claims.get("preferred_username")
            or claims.get("upn")
        )
    except Exception as e:
        logging.warning(f"Could not decode principal: {e}")
        return None


# Only identities on this domain may use the app, even if they hold a valid
# token in the Saragossa Entra tenant (blocks B2B guest accounts).
ALLOWED_EMAIL_DOMAINS = ("@saragossa.io",)


def require_auth(req: func.HttpRequest) -> tuple[str | None, func.HttpResponse | None]:
    """
    Returns (email, None) if authenticated with an approved Saragossa identity,
    or (None, 401/403 response) otherwise. Use at the top of every handler.
    """
    email = get_user_email(req)
    if not email:
        return None, func.HttpResponse("Unauthorised", status_code=401)
    if not email.lower().endswith(ALLOWED_EMAIL_DOMAINS):
        logging.warning(f"Blocked non-Saragossa identity: {email}")
        return None, func.HttpResponse("Forbidden — Saragossa accounts only", status_code=403)
    return email, None


def require_admin(req: func.HttpRequest) -> tuple[str | None, func.HttpResponse | None]:
    """
    Returns (email, None) if user is an admin, or (None, 403 response) if not.
    Admin = Director job title OR Bristol Finance & Compliance team member.
    Imports lazily to avoid circular imports.
    """
    email, err = require_auth(req)
    if err:
        return None, err

    from shared.dataverse import is_admin
    if not is_admin(email):
        return None, func.HttpResponse("Forbidden — admin access required", status_code=403)

    return email, None
