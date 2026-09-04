class MediaDownloaderError(ValueError):
    status_code = 500

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class InvalidMediaUrlError(MediaDownloaderError):
    status_code = 400


class UnsupportedPlatformError(MediaDownloaderError):
    status_code = 422


class PlatformParseError(MediaDownloaderError):
    status_code = 502


class PlatformAuthRequiredError(PlatformParseError):
    status_code = 502


class MediaRequestError(MediaDownloaderError):
    status_code = 502


class MediaTimeoutError(MediaRequestError):
    status_code = 504


class MediaDownloadError(MediaDownloaderError):
    status_code = 502
