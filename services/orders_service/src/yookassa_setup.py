import json
from types import SimpleNamespace
from urllib.parse import urlparse

from yookassa import Configuration

from settings import Settings

return_url = ""
fake = False


class LocalGatewayObject:
    def __init__(self, **data):
        self._data = dict(data)
        for key, value in data.items():
            setattr(self, key, value)

    def json(self) -> str:
        payload = {key: value for key, value in self._data.items() if key != "confirmation"}
        return json.dumps(payload, default=str)


def site_origin() -> str:
    parsed = urlparse(return_url or "http://localhost:3000/account/orders")
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "http://localhost:3000"


def fake_payment_url(order_id: str) -> str:
    return f"{site_origin()}/pay/test?order={order_id}"


def fake_deal(order_id: str) -> LocalGatewayObject:
    return LocalGatewayObject(id=f"fake-{order_id}", status="opened")


def fake_payment(order_id: str, status: str = "pending") -> LocalGatewayObject:
    return LocalGatewayObject(
        id=f"pay-{order_id}",
        status=status,
        confirmation=SimpleNamespace(confirmation_url=fake_payment_url(order_id)),
    )


def fake_payout(order_id: str) -> LocalGatewayObject:
    return LocalGatewayObject(id=f"po-{order_id}", status="succeeded")


def fake_refund(order_id: str) -> LocalGatewayObject:
    return LocalGatewayObject(id=f"rf-{order_id}", status="succeeded")


def configure_sdk(settings: Settings) -> None:
    global return_url, fake
    return_url = settings.yookassa_return_url
    fake = settings.yookassa_fake
    # Заказы в локальном режиме остаются заглушкой. Подписка Premium — обычный
    # платёж тестового магазина, поэтому ключи ЮKassa настраиваются всегда.
    Configuration.configure(
        settings.yookassa_account_id,
        settings.yookassa_secret_key,
        api_url=settings.yookassa_api_url,
        timeout=settings.yookassa_timeout,
        max_attempts=settings.yookassa_max_attempts,
        verify=settings.yookassa_verify,
    )
