from __future__ import annotations

from services.broker import BrokerService


def test_broker_url_encodes_default_vhost_and_credentials() -> None:
    broker = BrokerService(
        host="rabbitmq",
        port=5672,
        user="svc-user",
        password="pa:ss@word",
        vhost="/",
    )

    assert broker.url == "amqp://svc-user:pa%3Ass%40word@rabbitmq:5672/%2F"
