from yookassa import Configuration

from settings import Settings

return_url = ""


def configure_sdk(settings: Settings) -> None:
    Configuration.configure(
        settings.yookassa_account_id,
        settings.yookassa_secret_key,
        api_url=settings.yookassa_api_url,
        timeout=settings.yookassa_timeout,
        max_attempts=settings.yookassa_max_attempts,
        verify=settings.yookassa_verify,
    )
    global return_url
    return_url = settings.yookassa_return_url
