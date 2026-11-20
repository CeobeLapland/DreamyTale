from __future__ import annotations


class AdapterError(RuntimeError):
    code = "adapter_error"
    retryable = False

    def __init__(self, message: str, *, retryable: bool | None = None) -> None:
        if retryable is not None:
            self.retryable = retryable
        super().__init__(message)


class AdapterUnavailableError(AdapterError):
    code = "adapter_unavailable"
    retryable = True


class AdapterResponseError(AdapterError):
    code = "adapter_response_error"
    retryable = False