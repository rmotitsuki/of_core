"""Utilities module for of_core OpenFlow v0x01 operations."""
import json

from pyof.foundation.base import UBIntBase
from pyof.v0x01.controller2switch.common import (ConfigFlag, FlowStatsRequest,
                                                 PortStatsRequest)
from pyof.v0x01.controller2switch.set_config import SetConfig
from pyof.v0x01.controller2switch.stats_request import StatsRequest, StatsType
from pyof.v0x01.symmetric.echo_request import EchoRequest
from pyof.v0x01.symmetric.hello import Hello

from kytos.core import KytosEvent
from napps.kytos.of_core.utils import emit_message_out


class JSONEncoderOF10(json.JSONEncoder):
    """Custom JSON encoder for OF 1.0 flow representation.

    Make casting from UBInt8, UBInt16, UBInt32, UBInt64 to int.
    """

    def default(self, obj):  # pylint: disable=E0202,W0221
        """Make casting from UBInt8, UBInt16, UBInt32, UBInt64 to int."""
        if isinstance(obj, UBIntBase):
            return int(obj)
        return json.JSONEncoder.default(self, obj)


def update_flow_list(controller, switch):
    """Request flow stats from switches.

    Args:
        controller(:class:`~kytos.core.controller.Controller`):
            the controller being used.
        switch(:class:`~kytos.core.switch.Switch`):
            target to send a stats request.
    """
    body = FlowStatsRequest()
    stats_request = StatsRequest(
        body_type=StatsType.OFPST_FLOW,
        body=body)
    # req.pack()
    emit_message_out(controller, switch.connection, stats_request)


def request_port_stats(controller, switch):
    """Request port stats from switches.

    Args:
        controller(:class:`~kytos.core.controller.Controller`):
            the controller being used.
        switch(:class:`~kytos.core.switch.Switch`):
            target to send a stats request.
    """
    body = PortStatsRequest()
    stats_request = StatsRequest(
        body_type=StatsType.OFPST_PORT,
        body=body)
    # req.pack()
    emit_message_out(controller, switch.connection, stats_request)


def send_desc_request(controller, switch):
    """Send a description request to the switch.

    Args:
        controller(:class:`~kytos.core.controller.Controller`):
            the controller being used.
        switch(:class:`~kytos.core.switch.Switch`):
            target to send a stats request.
    """
    stats_request = StatsRequest(body_type=StatsType.OFPST_DESC)
    emit_message_out(controller, switch.connection, stats_request)


def handle_features_reply(controller, event):
    """Handle OF v0x01 features_reply message events.

    This is the end of the Handshake workflow of the OpenFlow Protocol.
    Parameters:
        controller (Controller): Controller being used.
        event (KytosEvent): Event with features reply message.

    """
    connection = event.source
    features_reply = event.content['message']
    dpid = features_reply.datapath_id.value

    switch = controller.get_switch_or_create(dpid=dpid,
                                             connection=connection)

    for port in features_reply.ports:
        switch.update_or_create_interface(
                port.port_no.value,
                name=port.name.value,
                address=port.hw_addr.value,
                state=port.state.value,
                features=port.curr)
        port_event = KytosEvent(name='kytos/of_core.switch.port.created',
                                content={
                                    'switch': switch.id,
                                    'port': port.port_no.value,
                                    'port_description': {
                                        'alias': port.name.value,
                                        'mac': port.hw_addr.value,
                                        'state': port.state.value
                                        }
                                    })
        controller.buffers.app.put(port_event)

    switch.update_features(features_reply)
    return switch


def send_echo(controller, switch):
    """Send echo request to a datapath.

    Keep the connection alive through symmetric echoes.
    """
    echo = EchoRequest(data=b'kytosd_10')
    emit_message_out(controller, switch.connection, echo)


def send_set_config(controller, switch):
    """Send a SetConfig message after the OpenFlow handshake."""
    set_config = SetConfig()
    set_config.flags = ConfigFlag.OFPC_FRAG_NORMAL
    set_config.miss_send_len = 0xffff       # Send the whole packet
    emit_message_out(controller, switch.connection, set_config)


def say_hello(controller, connection):
    """Send back a Hello packet with the same version as the switch."""
    hello = Hello()
    emit_message_out(controller, connection, hello)
