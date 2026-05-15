import logging
from typing import Any
import httpx
import requests
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient
import time
from functools import lru_cache

from server.models import (
    FitbitAuthResponse,
    MySettings,
)


def get_fitbit_auth_tokens(
    settings: MySettings,
    code: str,
) -> FitbitAuthResponse | dict[str, Any]:
    logging.info("GETTING token data")
    try:
        response = httpx.post(
            url="https://api.fitbit.com/oauth2/token",
            data={
                "client_id": settings.fitbit_client_id,
                "grant_type": "authorization_code",
                "code_verifier": settings.fitbit_code_verifier,
                "code": code,
            },
            headers={
                "Authorization": f"Basic {settings.fitbit_combined_secret()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout = 30
        )
    except Exception as e:
        logging.error(f"httpx failed: {e}")
        return {"error": "token request failed"}

    response_data = response.json()
    if response.status_code == 200:
        logging.info(f"Token data retrieved successfully.")
        return FitbitAuthResponse(**response_data)
    else:
        logging.error(f"Failed to retrieve token data.")
        return response_data


@lru_cache(maxsize=1)
def get_credential():
    return DefaultAzureCredential()

def get_cosmos_container(settings: MySettings):
    client = CosmosClient(url=settings.cosmosURL, credential=get_credential())
    database = client.get_database_client(settings.cosmosDB)
    return database.get_container_client(settings.cosmosContainer)


def upsert_with_retry(container, item, max_retries=3):
    for attempt in range(max_retries):
        try:
            container.upsert_item(item)
            return True
        except Exception as e:
            logging.error(f"Attempt {attempt+1} failed: {e}")

            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # exponential backoff: 1s, 2s, 4s
            else:
                logging.error("All retries failed - data not persisted")
                return False


def make_api_request_with_retry(access_token, endpoint, max_retries=3):
    url = f"https://api.fitbit.com/{endpoint}"
    headers = {"Authorization": f"Bearer {access_token}"}

    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            logging.info(f"API request to {endpoint} returned status code {response.status_code}")  

            if response.status_code >= 500:
                logging.error(f"Server error on attempt {attempt+1}: {response.status_code} - {response.text}")
                # raise RuntimeError(f"5xx {response.status_code}: {response.text}")

            if 400 <= response.status_code < 500:
                logging.error(f"Client error on attempt {attempt+1}: {response.status_code} - {response.text}")
                return {"status": response.status_code, "text": response.text}, True

            return response.json(), False

        except Exception as e:
            logging.error(f"Fitbit call failed attempt {attempt+1}/{max_retries}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                return {"error": str(e)}, True

def profile_pull(CurID, access_token):
    logging.info(f"Pulling Profile Data Fitbit ID: {CurID}")

    # Get the Profile Data to complete the participant table
    endpoint = '1/user/' + CurID + '/profile.json'
    if not access_token:
        logging.error(f"Missing access_token for Fitbit_ID={CurID}")
        Msg = f'FAILURE.\nTRY REGISTERING ATHLETE AGAIN.\nMissing access_token for Fitbit_ID={CurID}'
        return Msg

    logging.info(f"Fetching profile for Fitbit ID: {CurID} from endpoint: {endpoint}")
    profile, fail = make_api_request_with_retry(access_token, endpoint)
    logging.info(f"Fetched profile for Fitbit ID: {CurID}")
    
    if fail or not isinstance(profile, dict):
        logging.error(f"Failed to fetch/parse profile for Fitbit ID: {CurID}")
        Msg = f"FAILURE.\nTRY REGISTERING ATHLETE AGAIN.\nFailed to fetch/parse profile for Fitbit ID: {CurID}"
        return Msg

    if 'errors' in profile.keys():
        logging.error(f"Profile error for Fitbit ID: {CurID}")
        # Check to see if we can pull the error information
        ErrorInfo = profile.get('errors')
        # Assuming one error right now, but might want to combine all errors if others exist in the future
        if len(ErrorInfo) == 0:
            # Then just say that the Error is Unknown
            Msg = f'FAILURE.\nTRY REGISTERING ATHLETE AGAIN.\nUnknown error for Fitbit ID: {CurID}'
        elif len(ErrorInfo) > 0:
            # then just grab the first error message
            if isinstance(ErrorInfo, list) and len(ErrorInfo) > 0 and 'title' in ErrorInfo[0]:
                tMsg = ErrorInfo[0].get('title')
            elif isinstance(ErrorInfo, dict) and 'title' in ErrorInfo:
                tMsg = ErrorInfo.get('title')
            elif isinstance(ErrorInfo, str):
                tMsg = ErrorInfo
            else:
                tMsg = 'Unrecognized error format'  
            
            Msg = f"FAILURE.\nTRY REGISTERING ATHLETE AGAIN.\nProfile error for Fitbit ID: {CurID}: {tMsg}"
        return Msg
            
    elif 'error' in profile.keys():
        logging.error(f"Profile error for Fitbit ID: {CurID}")
        ErrorInfo = profile.get('error')
        # Assuming one error right now, but might want to combine all errors if others exist in the future
        if len(ErrorInfo) == 0:
            # Then just say that the Error is Unknown
            Msg = f'FAILURE.\nTRY REGISTERING ATHLETE AGAIN.\nUnknown error for Fitbit ID: {CurID}'
        elif len(ErrorInfo) > 0:
            # then just grab the first error message
            if isinstance(ErrorInfo, list) and len(ErrorInfo) > 0 and 'title' in ErrorInfo[0]:
                tMsg = ErrorInfo[0].get('title')
            elif isinstance(ErrorInfo, dict) and 'title' in ErrorInfo:
                tMsg = ErrorInfo.get('title')
            elif isinstance(ErrorInfo, str):
                tMsg = ErrorInfo
            else:
                tMsg = 'Unrecognized error format'  
            
            Msg = f"FAILURE.\nTRY REGISTERING ATHLETE AGAIN.\nProfile error for Fitbit ID: {CurID}: {tMsg}"
        return Msg
            
    else:
        logging.info(f"Processing valid profile for Fitbit ID: {CurID}")
        FirstName = profile.get('user', {}).get('firstName')
        LastName = profile.get('user', {}).get('lastName')
        Msg = f'Successfully connected: First Name: {FirstName}, Last Name: {LastName}, Fitbit ID: {CurID}'
    return Msg



def send_teams_message_webhook(webhook_url, message):
    # Set default color (black)
    theme_color = "00FF00"

    # If failure detected → make red
    if "failure" in message.lower():
        # Change the color to red for failures
        theme_color = "FF0000"

    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": theme_color,
        "summary": "Notification",
        "text": message.replace("\n", "<br>")
    }

    try:
        logging.info(f"Sending message to Teams webhook: {message}")
        response = requests.post(webhook_url, json = payload, timeout = 10)
        if not response.ok:
            logging.error(
                f"Failed to send message to Teams webhook. "
                f"Status code: {response.status_code}, "
                f"Response text: {response.text}"
            )
        else:
            logging.info("Teams message sent successfully")
    except Exception as e:
        logging.error(f"Exception occurred while sending message to Teams webhook: {e}")

