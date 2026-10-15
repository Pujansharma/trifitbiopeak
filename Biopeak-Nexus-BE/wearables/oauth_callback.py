"""Public ROOK OAuth browser return to the installed Biopeak mobile app.

ROOK redirects to a server-owned HTTPS URL and appends its client and member
identifiers as URL path segments. This callback is *navigation only*: it does
not create sessions, modify wearable connections, or assert OAuth success.
The authenticated app MUST refresh /devices/?refresh=true before showing
an authorized/connected state.
"""

import re
from urllib.parse import urlencode
from uuid import UUID

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.views.decorators.http import require_GET


ROOK_USER_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9-]{1,50}\Z")
APP_CALLBACK_URL = "biopeak://oauth-callback"


class BiopeakMobileRedirect(HttpResponseRedirect):
    """Permit only the application's fixed custom scheme for this response."""

    allowed_schemes = ["biopeak"]


@require_GET
def rook_oauth_callback(
    request: HttpRequest,
    client_uuid: str | None = None,
    user_id: str | None = None,
) -> HttpResponse:
    """Return the browser to React Native without trusting authorization hints."""
    parameters: dict[str, str] = {}

    if client_uuid is not None or user_id is not None:
        if not client_uuid or not user_id:
            return HttpResponseBadRequest("Incomplete ROOK callback identifiers.")
        try:
            client_identifier = UUID(client_uuid)
        except (ValueError, AttributeError):
            return HttpResponseBadRequest("Invalid ROOK client UUID.")
        if client_identifier.version != 4:
            return HttpResponseBadRequest("Invalid ROOK client UUID version.")
        if not ROOK_USER_IDENTIFIER_PATTERN.fullmatch(user_id):
            return HttpResponseBadRequest("Invalid ROOK user identifier.")
        parameters["client_uuid"] = str(client_identifier)
        parameters["user_id"] = user_id

    # Query values originate in an unauthenticated browser return and must
    # never be used by the app to establish authorization or create sessions.
    for parameter_name in ("status", "error"):
        parameter_value = request.GET.get(parameter_name, "")
        if parameter_value:
            parameters[parameter_name] = parameter_value[:200]

    query_string = urlencode(parameters)
    destination = (
        f"{APP_CALLBACK_URL}?{query_string}"
        if query_string
        else APP_CALLBACK_URL
    )
    response = BiopeakMobileRedirect(destination)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response
