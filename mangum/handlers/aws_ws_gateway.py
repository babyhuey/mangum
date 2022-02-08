import base64
import logging

from urllib.parse import urlencode, unquote
from typing import Dict, Any, TYPE_CHECKING, Tuple

from mangum.types import QueryParams

from .. import Response, Request

from ..types import Response, WsRequest
from .abstract_handler import AbstractHandler

logger = logging.getLogger("mangum")


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

    def __init__(
            self,
            trigger_event: Dict[str, Any],
            trigger_context: "LambdaContext",
            # api_gateway_base_path: str,
    ):
        super().__init__(trigger_event, trigger_context)
        # self.api_gateway_base_path = api_gateway_base_path

    @property
    def request(self) -> WsRequest:
        logger.debug("Starting request")
        request_context = self.trigger_event["requestContext"]
        logger.debug(f"Request context: {request_context}")
        server, headers = get_server_and_headers(self.trigger_event)
        source_ip = request_context.get("identity", {}).get("sourceIp")
        client = (source_ip, 0)
        headers_list = [[k.encode(), v.encode()] for k, v in headers.items()]
        query_string = self._encode_query_string()

        return WsRequest(
            headers=headers_list,
            path="/",
            scheme=headers.get("x-forwarded-proto", "wss"),
            query_string=query_string,
            server=server,
            client=client,
            trigger_event=self.trigger_event,
            trigger_context=self.trigger_context,
            event_type=self.TYPE,
        )

    @property
    def body(self) -> bytes:
        logger.debug("Starting body")
        body = self.trigger_event.get("body", b"") or b""
        logger.debug(f"Body is: {body}")
        if self.trigger_event.get("isBase64Encoded", False):
            return base64.b64decode(body)
        if not isinstance(body, bytes):
            body = body.encode()

        return body

    def _strip_base_path(self, path: str) -> str:
        if self.api_gateway_base_path and self.api_gateway_base_path != "/":
            if not self.api_gateway_base_path.startswith("/"):
                self.api_gateway_base_path = f"/{self.api_gateway_base_path}"
            if path.startswith(self.api_gateway_base_path):
                path = path[len(self.api_gateway_base_path):]
        return path

    def transform_response(self, response: Response) -> Dict[str, Any]:
        logger.debug("Transform Response")
        headers, multi_value_headers = self._handle_multi_value_headers(
            response.headers
        )

        body, is_base64_encoded = self._handle_base64_response_body(
            response.body, headers
        )

        return {
            "statusCode": response.status,
            "headers": headers,
            "multiValueHeaders": multi_value_headers,
            "body": body,
            "isBase64Encoded": is_base64_encoded,
        }

    def _encode_query_string(self) -> bytes:
        """
        Encodes the queryStringParameters.
        """

        params: QueryParams = self.trigger_event.get(
            "multiValueQueryStringParameters", {}
        )

        logger.debug(f"multiValueQueryStringParameters: {params}")
        if not params:
            params = self.trigger_event.get("queryStringParameters", {})
            logger.debug(f"queryStringParameters: {params}")
        if not params:
            logger.debug("Returning Null")
            return b""
        return urlencode(params, doseq=True).encode()
