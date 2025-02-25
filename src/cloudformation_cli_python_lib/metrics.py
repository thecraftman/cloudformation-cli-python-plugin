import datetime
import logging
from typing import Any, List, Mapping, Optional, Union

from botocore.exceptions import ClientError  # type: ignore

from .boto3_proxy import SessionProxy
from .interface import Action, HookInvocationPoint, MetricTypes, StandardUnit

LOG = logging.getLogger(__name__)

METRIC_NAMESPACE_ROOT = "AWS/CloudFormation"


def format_dimensions(dimensions: Mapping[str, str]) -> List[Mapping[str, str]]:
    return [{"Name": key, "Value": value} for key, value in dimensions.items()]


class MetricsPublisher:
    """A cloudwatch based metric publisher.\
    Given a resource type and session, \
    this publisher will publish metrics to CloudWatch.\
    Can be used with the MetricsPublisherProxy.

    Functions:
    ----------
    __init__: Initializes metric publisher with given session and resource type

    publish_exception_metric: Publishes an exception based metric

    publish_invocation_metric: Publishes a metric related to invocations

    publish_duration_metric: Publishes an duration metric

    publish_log_delivery_exception_metric: Publishes an log delivery exception metric
    """

    def __init__(self, session: SessionProxy, resource_type: str) -> None:
        self._client = session.client("cloudwatch")
        self._resource_type = resource_type
        self._namespace = self._make_namespace(self._resource_type)

    def publish_metric(  # pylint: disable-msg=too-many-arguments
        self,
        metric_name: MetricTypes,
        dimensions: Mapping[str, str],
        unit: StandardUnit,
        value: float,
        timestamp: datetime.datetime,
    ) -> None:
        try:
            self._client.put_metric_data(
                Namespace=self._namespace,
                MetricData=[
                    {
                        "MetricName": metric_name.name,
                        "Dimensions": format_dimensions(dimensions),
                        "Unit": unit.name,
                        "Timestamp": str(timestamp),
                        "Value": value,
                    }
                ],
            )

        except ClientError as e:
            LOG.error("An error occurred while publishing metrics: %s", str(e))

    def publish_exception_metric(
        self, timestamp: datetime.datetime, action: Action, error: Any
    ) -> None:
        dimensions: Mapping[str, str] = {
            "DimensionKeyActionType": action.name,
            "DimensionKeyExceptionType": str(type(error)),
            "DimensionKeyResourceType": self._resource_type,
        }
        self.publish_metric(
            metric_name=MetricTypes.HandlerException,
            dimensions=dimensions,
            unit=StandardUnit.Count,
            value=1.0,
            timestamp=timestamp,
        )

    def publish_invocation_metric(
        self, timestamp: datetime.datetime, action: Action
    ) -> None:
        dimensions = {
            "DimensionKeyActionType": action.name,
            "DimensionKeyResourceType": self._resource_type,
        }
        self.publish_metric(
            metric_name=MetricTypes.HandlerInvocationCount,
            dimensions=dimensions,
            unit=StandardUnit.Count,
            value=1.0,
            timestamp=timestamp,
        )

    def publish_duration_metric(
        self, timestamp: datetime.datetime, action: Action, milliseconds: float
    ) -> None:
        dimensions = {
            "DimensionKeyActionType": action.name,
            "DimensionKeyResourceType": self._resource_type,
        }

        self.publish_metric(
            metric_name=MetricTypes.HandlerInvocationDuration,
            dimensions=dimensions,
            unit=StandardUnit.Milliseconds,
            value=milliseconds,
            timestamp=timestamp,
        )

    def publish_log_delivery_exception_metric(
        self, timestamp: datetime.datetime, error: Any
    ) -> None:
        dimensions = {
            "DimensionKeyActionType": "ProviderLogDelivery",
            "DimensionKeyExceptionType": str(type(error)),
            "DimensionKeyResourceType": self._resource_type,
        }
        self.publish_metric(
            metric_name=MetricTypes.HandlerException,
            dimensions=dimensions,
            unit=StandardUnit.Count,
            value=1.0,
            timestamp=timestamp,
        )

    @staticmethod
    def _make_namespace(resource_type: str) -> str:
        suffix = resource_type.replace("::", "/")
        return f"{METRIC_NAMESPACE_ROOT}/{suffix}"


class HookMetricsPublisher(MetricsPublisher):
    def __init__(self, session: SessionProxy, hook_type: str, account_id: str) -> None:
        super().__init__(session, hook_type)
        self._hook_type = hook_type
        self._account_id = account_id
        self._namespace = self._make_hook_namespace(hook_type, account_id)

    # pylint: disable=arguments-differ
    def publish_exception_metric(  # type: ignore
        self,
        timestamp: datetime.datetime,
        invocation_point: HookInvocationPoint,
        error: Any,
    ) -> None:
        dimensions: Mapping[str, str] = {
            "DimensionKeyInvocationPointType": invocation_point.name,
            "DimensionKeyExceptionType": str(type(error)),
            "DimensionKeyHookType": self._hook_type,
        }
        self.publish_metric(
            metric_name=MetricTypes.HandlerException,
            dimensions=dimensions,
            unit=StandardUnit.Count,
            value=1.0,
            timestamp=timestamp,
        )

    # pylint: disable=arguments-differ
    def publish_invocation_metric(  # type: ignore
        self, timestamp: datetime.datetime, invocation_point: HookInvocationPoint
    ) -> None:
        dimensions = {
            "DimensionKeyInvocationPointType": invocation_point.name,
            "DimensionKeyHookType": self._hook_type,
        }
        self.publish_metric(
            metric_name=MetricTypes.HandlerInvocationCount,
            dimensions=dimensions,
            unit=StandardUnit.Count,
            value=1.0,
            timestamp=timestamp,
        )

    # pylint: disable=arguments-differ
    def publish_duration_metric(  # type: ignore
        self,
        timestamp: datetime.datetime,
        invocation_point: HookInvocationPoint,
        milliseconds: float,
    ) -> None:
        dimensions = {
            "DimensionKeyInvocationPointType": invocation_point.name,
            "DimensionKeyHookType": self._hook_type,
        }

        self.publish_metric(
            metric_name=MetricTypes.HandlerInvocationDuration,
            dimensions=dimensions,
            unit=StandardUnit.Milliseconds,
            value=milliseconds,
            timestamp=timestamp,
        )

    def publish_log_delivery_exception_metric(
        self, timestamp: datetime.datetime, error: Any
    ) -> None:
        dimensions = {
            "DimensionKeyInvocationPointType": "ProviderLogDelivery",
            "DimensionKeyExceptionType": str(type(error)),
            "DimensionKeyHookType": self._hook_type,
        }
        self.publish_metric(
            metric_name=MetricTypes.HandlerException,
            dimensions=dimensions,
            unit=StandardUnit.Count,
            value=1.0,
            timestamp=timestamp,
        )

    @staticmethod
    def _make_hook_namespace(hook_type: str, account_id: str) -> str:
        suffix = hook_type.replace("::", "/")
        return f"{METRIC_NAMESPACE_ROOT}/{account_id}/{suffix}"


class MetricsPublisherProxy:
    """A proxy for publishing metrics to multiple publishers. \
    Iterates over available publishers and publishes.

    Functions:
    ----------
    add_metrics_publisher: Adds a metrics publisher to the list of publishers

    publish_exception_metric: \
    Publishes an exception based metric to the list of publishers

    publish_invocation_metric: \
    Publishes a metric related to invocations to the list of publishers

    publish_duration_metric: Publishes a duration metric to the list of publishers

    publish_log_delivery_exception_metric: \
     Publishes a log delivery exception metric to the list of publishers
    """

    def __init__(self) -> None:
        self._publishers: List[MetricsPublisher] = []

    def add_metrics_publisher(
        self, session: Optional[SessionProxy], type_name: Optional[str]
    ) -> None:
        if session and type_name:
            publisher = MetricsPublisher(session, type_name)
            self._publishers.append(publisher)

    def add_hook_metrics_publisher(
        self,
        session: Optional[SessionProxy],
        type_name: Optional[str],
        account_id: Optional[str],
    ) -> None:
        if session and type_name and account_id:
            publisher = HookMetricsPublisher(session, type_name, account_id)
            self._publishers.append(publisher)

    def publish_exception_metric(
        self,
        timestamp: datetime.datetime,
        action: Union[Action, HookInvocationPoint],
        error: Any,
    ) -> None:
        for publisher in self._publishers:
            publisher.publish_exception_metric(timestamp, action, error)  # type: ignore

    def publish_invocation_metric(
        self, timestamp: datetime.datetime, action: Union[Action, HookInvocationPoint]
    ) -> None:
        for publisher in self._publishers:
            publisher.publish_invocation_metric(timestamp, action)  # type: ignore

    # pylint: disable=line-too-long
    def publish_duration_metric(
        self,
        timestamp: datetime.datetime,
        action: Union[Action, HookInvocationPoint],
        milliseconds: float,
    ) -> None:
        # fmt off
        for publisher in self._publishers:
            publisher.publish_duration_metric(timestamp, action, milliseconds)  # type: ignore
        # fmt on

    def publish_log_delivery_exception_metric(
        self, timestamp: datetime.datetime, error: Any
    ) -> None:
        for publisher in self._publishers:
            publisher.publish_log_delivery_exception_metric(timestamp, error)
