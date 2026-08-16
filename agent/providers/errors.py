import httpx


class ProviderError(RuntimeError):
    pass


class ProviderAuthenticationError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderTimeoutError(ProviderError):
    pass


class ProviderUnavailableError(ProviderError):
    pass


class ModelNotFoundError(ProviderError):
    pass


class ModelCapabilityError(ProviderError):
    pass


class ContextLengthError(ProviderError):
    pass


class TokenLimitError(ProviderError):
    pass


class InvalidRequestError(ProviderError):
    pass


def raise_for_response(provider: str, response: httpx.Response) -> None:
    """Map provider HTTP status codes to the shared exception contract."""
    status = response.status_code
    if status in {401, 403}:
        raise ProviderAuthenticationError(f'{provider} authentication failed')
    if status == 404:
        raise ModelNotFoundError(f'{provider} model or endpoint not found')
    if status == 429:
        raise ProviderRateLimitError(f'{provider} rate limited')
    if 400 <= status < 500:
        raise InvalidRequestError(f'{provider} rejected the request')
    if status >= 500:
        raise ProviderUnavailableError(f'{provider} unavailable')
    response.raise_for_status()


def map_http_error(provider: str, error: Exception) -> ProviderError:
    if isinstance(error, ProviderError):
        return error
    if isinstance(error, httpx.TimeoutException):
        return ProviderTimeoutError(f'{provider} request timed out')
    if isinstance(error, httpx.HTTPError):
        return ProviderUnavailableError(f'{provider} network request failed')
    if isinstance(error, (KeyError, IndexError, TypeError, ValueError)):
        return ProviderUnavailableError(f'{provider} returned an invalid response')
    return ProviderUnavailableError(f'{provider} request failed')
