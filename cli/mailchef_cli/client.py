import httpx

from mailchef_cli.config import CLIConfig


class ClientError(Exception):
    def __init__(self, detail: str, status_code: int):
        super().__init__(detail)
        self.status_code = status_code


class MailChefClient:
    def __init__(self, config: CLIConfig):
        self._http = httpx.Client(
            base_url=config.backend_url,
            headers={"Authorization": f"Bearer {config.api_token}"},
            timeout=120.0,
        )

    def get(self, path: str, params: dict | None = None):
        return _handle(self._http.get(path, params=_clean(params)))

    def post(self, path: str, json_body: dict | None = None):
        return _handle(self._http.post(path, json=json_body or {}))


def _clean(params: dict | None) -> dict | None:
    if params is None:
        return None
    return {k: v for k, v in params.items() if v is not None and v is not False}


def _handle(response: httpx.Response):
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ClientError(str(detail), response.status_code)
    return response.json()
