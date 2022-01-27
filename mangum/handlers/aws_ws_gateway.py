import base64

from urllib.parse import urlencode, unquote
from typing import Dict, Any, TYPE_CHECKING, Tuple

from mangum.types import QueryParams

from .. import Response, Request

from ..types import Response, WsRequest
from .abstract_handler import AbstractHandler


def get_server_and_headers(event: Dict[str, Any]) -> Tuple:  # pragma: no cover
    if event.get("multiValueHeaders"):
        headers = {
            k.lower(): ", ".join(v) if isinstance(v, list) else ""
            for k, v in event.get("multiValueHeaders", {}).items()
        }
    elif event.get("headers"):
        headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    else:
        headers = {}

    # Subprotocols are not supported, so drop Sec-WebSocket-Protocol to be safe
    headers.pop("sec-websocket-protocol", None)

    server_name = headers.get("host", "mangum")
    if ":" not in server_name:
        server_port = headers.get("x-forwarded-port", 80)
    else:
        server_name, server_port = server_name.split(":")
    server = (server_name, int(server_port))

    return server, headers


class AwsWsGateway(AbstractHandler):
    """
    Handles AWS API Gateway Websocket events, transforming
    them into ASGI Scope and handling responses

    See: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-input-format  # noqa: E501
    """

    TYPE = "AWS_WS_GATEWAY"

    @property
    def request(self) -> WsRequest:
        logger.info("Starting request")
        request_context = self.trigger_event["requestContext"]
        server, headers = get_server_and_headers(self.trigger_event)
        source_ip = request_context.get("identity", {}).get("sourceIp")
        client = (source_ip, 0)
        headers_list = [[k.encode(), v.encode()] for k, v in headers.items()]

        return WsRequest(
            headers=headers_list,
            path="/",
            scheme=headers.get("x-forwarded-proto", "wss"),
            query_string=self._encode_query_string(),

            server=server,
            client=client,
            trigger_event=self.trigger_event,
            trigger_context=self.trigger_context,
            event_type=self.TYPE,
        )

    @property
    def body(self) -> bytes:
        logger.info("Starting body")
        body = self.trigger_event.get("body", b"") or b""

        if self.trigger_event.get("isBase64Encoded", False):
            return base64.b64decode(body)
        if not isinstance(body, bytes):
            body = body.encode()

        return body

    def transform_response(self, response: Response) -> Dict[str, Any]:

        logger.info("Transform Response")
        return {"statusCode": response.status}


def _encode_query_string(self) -> bytes:
    """
    Encodes the queryStringParameters.
    """

    params: QueryParams = self.trigger_event.get(
        "multiValueQueryStringParameters", {}
    )

    logger.info(f"multiValueQueryStringParameters: {params}")
    if not params:
        params = self.trigger_event.get("queryStringParameters", {})
        logger.info(f"queryStringParameters: {params}")
    if not params:
        logger.info("Returning Null")
        return b""
    return urlencode(params, doseq=True).encode()
