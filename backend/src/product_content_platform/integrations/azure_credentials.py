from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Callable
from urllib.parse import urlparse


COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
AI_FOUNDRY_SCOPE = "https://ai.azure.com/.default"
SUPPORTED_AUTH_MODES = {"static", "managed_identity", "default_credential"}
TokenProvider = Callable[[], str]


class AzureCredentialConfigurationError(RuntimeError):
    pass


class AzureCognitiveServicesTokenProvider:
    """Callable token provider backed by azure-identity.

    Azure Identity owns token caching and refresh. Calling this provider for every
    request is therefore inexpensive and avoids storing an expiring access token in
    application configuration.
    """

    def __init__(self, credential: Any, scope: str = COGNITIVE_SERVICES_SCOPE) -> None:
        self._credential = credential
        self._scope = scope

    def __call__(self) -> str:
        return str(self._credential.get_token(self._scope).token)


def token_scope_for_endpoint(endpoint: str | None) -> str:
    """Return the Entra audience required by an Azure AI data-plane endpoint."""

    if not endpoint:
        return COGNITIVE_SERVICES_SCOPE
    parsed = urlparse(endpoint.strip())
    host = parsed.hostname.casefold() if parsed.hostname else ""
    path = parsed.path.casefold()
    if host.endswith(".services.ai.azure.com") or "/api/projects/" in path:
        return AI_FOUNDRY_SCOPE
    return COGNITIVE_SERVICES_SCOPE


def token_provider_from_env(
    *,
    endpoint: str | None = None,
    scope: str | None = None,
) -> TokenProvider | None:
    """Build the configured Entra token provider, or return None for static auth."""

    mode = os.environ.get("AZURE_AUTH_MODE", "static").strip().casefold()
    if mode not in SUPPORTED_AUTH_MODES:
        supported = ", ".join(sorted(SUPPORTED_AUTH_MODES))
        raise AzureCredentialConfigurationError(
            f"Unsupported AZURE_AUTH_MODE={mode!r}. Expected one of: {supported}."
        )
    if mode == "static":
        return None

    client_id = (
        os.environ.get("AZURE_MANAGED_IDENTITY_CLIENT_ID")
        or os.environ.get("AZURE_CLIENT_ID")
        or ""
    ).strip()
    credential = _credential(mode, client_id)
    resolved_scope = scope or token_scope_for_endpoint(endpoint)
    return AzureCognitiveServicesTokenProvider(credential, resolved_scope)


@lru_cache(maxsize=4)
def _credential(mode: str, client_id: str) -> Any:
    try:
        from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
    except ImportError as exc:
        raise AzureCredentialConfigurationError(
            "Managed Identity authentication requires the azure-identity package. "
            "Install the backend project dependencies before starting the service."
        ) from exc

    if mode == "managed_identity":
        return ManagedIdentityCredential(client_id=client_id or None)
    return DefaultAzureCredential(managed_identity_client_id=client_id or None)
