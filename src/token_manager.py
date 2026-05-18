import httpx
import jwt
import json
import os
import stat
import logging
import tempfile

# Module-level logger — do NOT disable logging globally; callers control their level.
logger = logging.getLogger(__name__)


class TokenManager:
    def __init__(self, agent_id: str, agent_key: str, auth_api_url: str) -> None:
        self.agent_id = agent_id
        self.agent_key = agent_key
        self.auth_api_url = auth_api_url

        # Store tokens in a user-only-readable file (mode 0600).
        self.cache_file = os.path.join(tempfile.gettempdir(), f"neo_token_{os.getuid()}.json")

    def _request(
        self,
        method: str,
        endpoint: str,
        headers: dict | None = None,
        params: dict | None = None,
        data: dict | None = None,
    ) -> dict:
        url = f"{self.auth_api_url}{endpoint}"
        try:
            response = httpx.request(method, url, headers=headers, params=params, json=data)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error("Request failed for %s: %s", endpoint, e)
            raise
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error %s for %s: %s", e.response.status_code, endpoint, e.response.text)
            raise

    def _get_refresh_token(self) -> str:
        logger.info("Requesting refresh token...")
        response = self._request(
            "POST",
            f"/auth/agents/{self.agent_id}/token",
            headers={"Content-Type": "application/json", "X-Api-Key": self.agent_key},
        )
        return response["refresh_token"]

    def _get_access_token(self, refresh_token: str) -> str:
        logger.info("Requesting access token using refresh token...")
        response = self._request(
            "PUT",
            f"/auth/agents/{self.agent_id}/token",
            headers={"Content-Type": "application/json", "X-Api-Key": self.agent_key},
            params={"refresh_token": refresh_token},
        )
        return response["access_token"]

    def _is_token_expired(self, token: str | None) -> bool:
        if not token:
            return True
        try:
            jwt.decode(token, options={"verify_signature": False, "verify_exp": True})
            return False
        except jwt.ExpiredSignatureError:
            logger.info("Token has expired.")
            return True
        except Exception as e:
            logger.warning("Token validation failed: %s", e)
            return True

    def _load_tokens_from_cache(self) -> dict | None:
        if not os.path.exists(self.cache_file):
            return None
        # Reject cache file if it is readable by anyone other than the owner.
        try:
            file_stat = os.stat(self.cache_file)
            if file_stat.st_mode & (stat.S_IRGRP | stat.S_IROTH):
                logger.warning("Token cache has insecure permissions — removing it.")
                os.remove(self.cache_file)
                return None
        except OSError:
            return None
        try:
            with open(self.cache_file, "r") as f:
                tokens = json.load(f)
            if self._is_token_expired(tokens.get("access_token")) and self._is_token_expired(
                tokens.get("refresh_token")
            ):
                logger.warning("Both access and refresh tokens are expired. Clearing cache.")
                os.remove(self.cache_file)
                return None
            return tokens
        except (json.JSONDecodeError, KeyError):
            logger.warning("Token cache is corrupted — ignoring it.")
            return None

    def _save_tokens_to_cache(self, access_token: str, refresh_token: str) -> None:
        # Use os.open with O_CREAT|O_WRONLY|O_TRUNC and mode 0o600 so the file
        # is never world-readable, even briefly while being written.
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(self.cache_file, flags, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"access_token": access_token, "refresh_token": refresh_token}, f)
        except Exception:
            # fd is already closed by fdopen on exception; best-effort cleanup.
            try:
                os.remove(self.cache_file)
            except OSError:
                pass
            raise

    def get_valid_access_token(self) -> str:
        try:
            tokens = self._load_tokens_from_cache()

            if tokens and not self._is_token_expired(tokens["access_token"]):
                logger.info("Using valid cached access token.")
                return tokens["access_token"]

            if tokens and not self._is_token_expired(tokens["refresh_token"]):
                logger.info("Cached access token expired. Refreshing...")
                refresh_token = tokens["refresh_token"]
            else:
                logger.info("No valid refresh token found. Requesting a new one...")
                refresh_token = self._get_refresh_token()

            access_token = self._get_access_token(refresh_token)
            self._save_tokens_to_cache(access_token, refresh_token)
            return access_token

        except Exception as e:
            logger.error("Failed to get a valid access token: %s", e)
            raise