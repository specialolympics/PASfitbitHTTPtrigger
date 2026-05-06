import base64
from datetime import datetime, UTC
import uuid
from pydantic import BaseModel, Field, field_serializer
from pydantic_settings import BaseSettings, SettingsConfigDict


class MySettings(BaseSettings):
    """Settings for the application

    Reads from `.env`, but can be overriden by ENVIRONMENT variables.

    This is hugely beneficial since it lets us have env vars locally for testing
    and then production ones are set separately.
    """

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )
    """Configure model to use .env and ignore casing"""

    fitbit_client_id: str = Field()
    fitbit_client_secret: str = Field()
    fitbit_code_verifier: str = Field()
    redirect_url: str = Field()
    teams_webhook_url: str = Field()
    cosmosURL: str = Field()
    cosmosDB: str = Field()
    cosmosContainer: str = Field()

    def fitbit_combined_secret(self) -> str:
        """Combine the client id and secret per auth flow requirements

        Uses:
            id_: client id
            secret: client secret

        Returns:
            str: combined string, base64 encoded, with ":" separator
        """
        combined_string = self.fitbit_client_id + ":" + self.fitbit_client_secret
        combined_bytes = combined_string.encode("utf-8")
        encoded_bytes = base64.urlsafe_b64encode(combined_bytes)
        encoded_string = encoded_bytes.decode("utf-8")
        return encoded_string


class TokenTableData(BaseModel):
    id: str = Field()
    user_id: str = Field()
    access_token: str = Field()
    refresh_token: str = Field()
    created_at: datetime = Field()
    last_refresh: datetime = Field()

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime, _info) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")

    @field_serializer("last_refresh")
    def serialize_last_refresh(self, value: datetime, _info) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")


class FitbitAuthResponse(BaseModel):
    user_id: str = Field()
    access_token: str = Field()
    refresh_token: str = Field()
    expires_in: int = Field()
    scope: str = Field()
    token_type: str = Field()

    def to_token_data(self) -> TokenTableData:
        data = TokenTableData(
            id=str(uuid.uuid4()),
            user_id=self.user_id,
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            created_at=datetime.now(UTC),
            last_refresh=datetime.now(UTC),
        )
        return data



