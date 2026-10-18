from unittest.mock import patch

from settings import Settings
from yookassa_setup import configure_sdk


def test_sdk_is_configured_from_settings():
    settings = Settings(
        database_url="postgresql+asyncpg://localhost/orders",
        yookassa_account_id="shop-1",
        yookassa_secret_key="secret-1",
        yookassa_return_url="https://shop.example/return",
        yookassa_api_url="https://api.yookassa.ru/v3",
        yookassa_timeout=30,
        yookassa_max_attempts=2,
        yookassa_verify=True,
    )

    with patch("yookassa_setup.Configuration.configure") as configure:
        configure_sdk(settings)

    configure.assert_called_once_with(
        "shop-1",
        "secret-1",
        api_url="https://api.yookassa.ru/v3",
        timeout=30,
        max_attempts=2,
        verify=True,
    )
    from yookassa_setup import return_url

    assert return_url == "https://shop.example/return"
