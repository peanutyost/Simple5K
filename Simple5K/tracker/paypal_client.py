"""
PayPal REST API client initialisation (Orders v2).

Usage:
    from .paypal_client import get_paypal_client
    client = get_paypal_client()
    orders_controller = client.orders
"""
import logging

from django.conf import settings

from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient
from paypalserversdk.configuration import Environment
from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials

logger = logging.getLogger(__name__)


def get_paypal_client():
    """Return a configured PaypalServersdkClient. Creates a new instance each call
    (the SDK handles OAuth token caching internally)."""
    env = Environment.SANDBOX if settings.PAYPAL_SANDBOX else Environment.PRODUCTION
    return PaypalServersdkClient(
        client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
            o_auth_client_id=settings.PAYPAL_CLIENT_ID,
            o_auth_client_secret=settings.PAYPAL_CLIENT_SECRET,
        ),
        environment=env,
    )
