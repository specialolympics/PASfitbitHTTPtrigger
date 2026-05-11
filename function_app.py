import json
import logging
import azure.functions as func
from server import utils as u
from server.models import MySettings

# Creation of Function app triggered by HTTP
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.function_name(name="fitbittoken")
@app.route(route="fitbittoken")
def fitbittoken(req: func.HttpRequest) -> func.HttpResponse:
    settings = MySettings()
    logging.info(f"handling req for url")
    code = req.params.get("code")
    logging.info(f"got code")
    if code is None:
        return func.HttpResponse(
            status_code=404,
            body=json.dumps({"message": "Code querystring not found in: {req.url}"}),
            mimetype="application/json",
        )
    token_data = u.get_fitbit_auth_tokens(settings = settings, code = code)
    if isinstance(token_data, dict):
        return func.HttpResponse(
            status_code=404,
            body=json.dumps(token_data),
            mimetype="application/json",
        )
    logging.info(f"got token data.")
    token_data = token_data.to_token_data()
    logging.info(f"created table data.")
    token_data = token_data.model_dump()
    logging.info(f"dumped token data to dict.")

    Msg = u.profile_pull(token_data["user_id"], token_data["access_token"])

    container = u.get_cosmos_container(settings = settings)
    
    success = u.upsert_with_retry(container, token_data)

    if success:
        logging.info("Successfully upserted token data.")
        TeamsMSG = "Token data Successfully uploaded. " + Msg
    else:
        logging.error("Failed to upsert token data after retries.")
        TeamsMSG = "Failed to upload token data. " + Msg
    
    logging.info("Ready to send teams message.")
    u.send_teams_message_webhook(settings.teams_webhook_url, TeamsMSG)

    return func.HttpResponse(
        settings.redirect_url,
        headers={"Location": settings.redirect_url},
        status_code=302,
    )


