"""NApp responsible for the main OpenFlow basic operations."""

import time
from threading import Lock

from pyof.foundation.exceptions import UnpackException
from pyof.foundation.network_types import Ethernet, EtherType
from pyof.utils import PYOF_VERSION_LIBS, unpack
from pyof.v0x01.common.header import Type
from pyof.v0x01.controller2switch.common import StatsType
from pyof.v0x04.controller2switch.common import MultipartType

from kytos.core import KytosEvent, KytosNApp, log
from kytos.core.connection import ConnectionState
from kytos.core.helpers import listen_to, run_on_thread
from kytos.core.interface import Interface
from napps.kytos.of_core import settings
from napps.kytos.of_core.utils import (GenericHello, NegotiationException,
                                       emit_message_in, emit_message_out,
                                       of_slicer)
from napps.kytos.of_core.v0x01 import utils as of_core_v0x01_utils
from napps.kytos.of_core.v0x01.flow import Flow as Flow01
from napps.kytos.of_core.v0x04 import utils as of_core_v0x04_utils
from napps.kytos.of_core.v0x04.flow import Flow as Flow04


class Main(KytosNApp):
    """Main class of the NApp responsible for OpenFlow basic operations."""

    # Keep track of multiple multipart replies from our own request only.
    # Assume that all replies are received before setting a new xid. If
    # that is not the case (i.e., overlapping replies), we skip up to X
    # cycles before cleaning up pending requests and getting a fresh start
    _multipart_replies_xids = {}
    _multipart_replies_flows = {}
    _multipart_replies_ports = {}

    def setup(self):
        """App initialization (used instead of ``__init__``).

        The setup method is automatically called by the run method.
        Users shouldn't call this method directly.
        """
        self.of_core_version_utils = {0x01: of_core_v0x01_utils,
                                      0x04: of_core_v0x04_utils}
        self.execute_as_loop(settings.STATS_INTERVAL)
        self._multipart_flows_lock = {}
        self._multipart_replies_xids_lock = {}
        self._connection_lock = {}

        # Per switch delay to request flow/port stats, to avoid all request
        # being sent together and increase the overhead on the controller
        self.switch_req_stats_delay = {}

    def execute(self):
        """Run once on app 'start' or in a loop.

        The execute method is called by the run method of KytosNApp class.
        Users shouldn't call this method directly.
        """
        for switch in self.controller.switches.values():
            if switch.is_connected():
                self._request_flow_list(switch)
                if settings.SEND_ECHO_REQUESTS:
                    version_utils = \
                        self.of_core_version_utils[switch.
                                                   connection.protocol.version]
                    version_utils.send_echo(self.controller, switch)

    def _check_overlapping_multipart_request(self, switch):
        """Check overlapping multipart stats request (OF 1.3 only)."""
        current_req = self._multipart_replies_xids.get(switch.id, {})
        if ('flows' in current_req or 'ports' in current_req) and \
           current_req.get('skipped', 0) < settings.STATS_REQ_SKIP:
            log.info("Overlapping stats request: switch %s flows_xid %s"
                     " ports_xid %s", switch.id, current_req.get('flows'),
                     current_req.get('ports'))
            current_req['skipped'] = current_req.get('skipped', 0) + 1
            return True

        if switch.id in self._multipart_replies_flows:
            del self._multipart_replies_flows[switch.id]
        if switch.id in self._multipart_replies_ports:
            del self._multipart_replies_ports[switch.id]
        return False

    def _get_switch_req_stats_delay(self, switch):
        if switch.id in self.switch_req_stats_delay:
            return self.switch_req_stats_delay[switch.id]
        last = self.switch_req_stats_delay.get('last', 0)
        max_delay = settings.STATS_INTERVAL/2
        next_delay = (last + max_delay/10) % max_delay
        self.switch_req_stats_delay[switch.id] = next_delay
        self.switch_req_stats_delay['last'] = next_delay
        return next_delay

    @run_on_thread
    def _request_flow_list(self, switch):
        """Send flow stats request to a connected switch."""
        time.sleep(self._get_switch_req_stats_delay(switch))
        of_version = switch.connection.protocol.version
        if of_version == 0x01:
            of_core_v0x01_utils.update_flow_list(self.controller, switch)
            of_core_v0x01_utils.request_port_stats(self.controller, switch)
        elif of_version == 0x04:
            if self._check_overlapping_multipart_request(switch):
                return

            xid_flows = of_core_v0x04_utils.update_flow_list(self.controller,
                                                             switch)
            xid_ports = of_core_v0x04_utils.request_port_stats(self.controller,
                                                               switch)
            self._multipart_replies_xids[switch.id] = {'flows': xid_flows,
                                                       int(xid_flows): 0,
                                                       'ports': xid_ports}
            if switch.id not in self._multipart_replies_xids_lock:
                self._multipart_replies_xids_lock[switch.id] = Lock()

    @listen_to('kytos/of_core.v0x01.messages.in.ofpt_stats_reply')
    def on_stats_reply(self, event):
        """Handle stats replies for v0x01 switches.

        Args:
            event (:class:`~kytos.core.events.KytosEvent):
                Event with ofpt_stats_reply in message.
        """
        self.handle_stats_reply(event)

    def handle_stats_reply(self, event):
        """Handle stats replies for v0x01 switches."""
        switch = event.source.switch
        msg = event.content['message']
        if msg.body_type == StatsType.OFPST_FLOW:
            switch.flows = [Flow01.from_of_flow_stats(f, switch)
                            for f in msg.body]
            event_raw = KytosEvent(
                name='kytos/of_core.flow_stats.received',
                content={'switch': switch})
            self.controller.buffers.app.put(event_raw)
        elif msg.body_type == StatsType.OFPST_PORT:
            port_stats = [of_port_stats for of_port_stats in msg.body]
            port_stats_event = KytosEvent(
                name="kytos/of_core.port_stats",
                content={
                    'switch': switch,
                    'port_stats': port_stats
                    })
            self.controller.buffers.app.put(port_stats_event)
        elif msg.body_type == StatsType.OFPST_DESC:
            switch.update_description(msg.body)

    @listen_to('kytos/of_core.v0x0[14].messages.in.ofpt_features_reply')
    def on_features_reply(self, event):
        """Handle kytos/of_core.messages.in.ofpt_features_reply event.

        This is the end of the Handshake workflow of the OpenFlow Protocol.

        Args:
            event (KytosEvent): Event with features reply message.
        """
        self.handle_features_reply(event)

    def handle_features_reply(self, event):
        """Handle kytos/of_core.messages.in.ofpt_features_reply event."""
        connection = event.source
        version_utils = self.of_core_version_utils[connection.protocol.version]
        switch = version_utils.handle_features_reply(self.controller, event)
        switch.update_lastseen()

        if (connection.is_during_setup() and
                connection.protocol.state == 'waiting_features_reply'):
            connection.protocol.state = 'handshake_complete'
            connection.set_established_state()
            version_utils.send_desc_request(self.controller, switch)
            if settings.SEND_SET_CONFIG:
                version_utils.send_set_config(self.controller, switch)
            log.info('Connection %s, Switch %s: OPENFLOW HANDSHAKE COMPLETE',
                     connection.id, switch.dpid)
            event_raw = KytosEvent(
                name='kytos/of_core.handshake.completed',
                content={'switch': switch})
            self.controller.buffers.app.put(event_raw)

    @listen_to('kytos/of_core.handshake.completed')
    def on_handshake_completed_request_flow_list(self, event):
        """Request an flow list right after the handshake is completed.

        Args:
            event (KytosEvent): Event with the switch' handshake completed
        """
        switch = event.content['switch']
        if switch.is_enabled():
            self._request_flow_list(switch)

    @listen_to('kytos/of_core.v0x04.messages.in.ofpt_multipart_reply')
    def on_multipart_reply(self, event):
        """Handle multipart replies for v0x04 switches.

        Args:
            event (:class:`~kytos.core.events.KytosEvent):
                Event with ofpt_multipart_reply in message.
        """
        self.handle_multipart_reply(event)

    def handle_multipart_reply(self, event):
        """Handle multipart replies for v0x04 switches."""
        reply = event.content['message']
        switch = event.source.switch

        if reply.multipart_type == MultipartType.OFPMP_FLOW:
            self._handle_multipart_flow_stats(reply, switch)
        elif reply.multipart_type == MultipartType.OFPMP_PORT_STATS:
            self._handle_multipart_port_stats(reply, switch)
        elif reply.multipart_type == MultipartType.OFPMP_PORT_DESC:
            of_core_v0x04_utils.handle_port_desc(self.controller, switch,
                                                 reply.body)
        elif reply.multipart_type == MultipartType.OFPMP_DESC:
            switch.update_description(reply.body)

    def _handle_multipart_flow_stats(self, reply, switch):
        """Update switch flows after all replies are received."""
        if self._is_multipart_reply_ours(reply, switch, 'flows'):
            # Get all flows from the reply
            flows = [Flow04.from_of_flow_stats(of_flow_stats, switch)
                     for of_flow_stats in reply.body]
            self._multipart_flows_lock.setdefault(switch.id, Lock())
            # Get existent flows from the same xid (or create an empty list)
            with self._multipart_flows_lock[switch.id]:
                all_flows = self._multipart_replies_flows.setdefault(switch.id,
                                                                     [])
                all_flows.extend(flows)

            xid = int(reply.header.xid)
            if xid in self._multipart_replies_xids.get(switch.id, {}):
                with self._multipart_replies_xids_lock[switch.id]:
                    self._multipart_replies_xids[switch.id][xid] -= 1

            if reply.flags.value % 2 == 0:  # Last bit means more replies
                # make sure no more parts are missing, wait at most half of
                # STATS_INTERVAL
                _wait_sleep = 0.05
                _wait_count = 0
                while _wait_count < settings.STATS_INTERVAL/2:
                    if self._multipart_replies_xids.get(switch.id,
                                                        {}).get(xid, 0) > 0:
                        time.sleep(_wait_sleep)
                    else:
                        break
                    _wait_count += _wait_sleep
                try:
                    self._update_switch_flows(switch)
                except KeyError:
                    log.error("Skipped flow stats reply due to error when"
                              f"updating switch {switch.id}, xid {xid}")
                    return
                event_raw = KytosEvent(
                    name='kytos/of_core.flow_stats.received',
                    content={'switch': switch})
                self.controller.buffers.app.put(event_raw)

    def _handle_multipart_port_stats(self, reply, switch):
        """Emit an event about new port stats."""
        if self._is_multipart_reply_ours(reply, switch, 'ports'):
            port_stats = [of_port_stats for of_port_stats in reply.body]
            all_port_stats = self._multipart_replies_ports.setdefault(
                switch.id, []
            )
            all_port_stats.extend(port_stats)
            if reply.flags.value % 2 == 0:
                self._new_port_stats(switch)

    def _update_switch_flows(self, switch):
        """Update controllers' switch flow list and clean resources."""
        switch.flows = self._multipart_replies_flows[switch.id]
        xid_flows = int(self._multipart_replies_xids[switch.id]['flows'])
        del self._multipart_replies_flows[switch.id]
        del self._multipart_replies_xids[switch.id]['flows']
        if xid_flows in self._multipart_replies_xids[switch.id]:
            del self._multipart_replies_xids[switch.id][xid_flows]

    def _new_port_stats(self, switch):
        """Send an event with the new port stats and clean resources."""
        all_port_stats = self._multipart_replies_ports[switch.id]
        del self._multipart_replies_ports[switch.id]
        del self._multipart_replies_xids[switch.id]['ports']
        port_stats_event = KytosEvent(
            name=f"kytos/of_core.port_stats",
            content={
                'switch': switch,
                'port_stats': all_port_stats
                })
        self.controller.buffers.app.put(port_stats_event)

    def _is_multipart_reply_ours(self, reply, switch, stat):
        """Return whether we are expecting the reply."""
        if switch.id in self._multipart_replies_xids:
            sent_xid = self._multipart_replies_xids[switch.id].get(stat)
            if sent_xid == reply.header.xid:
                return True
        return False

    @listen_to('kytos/core.openflow.raw.in')
    def on_raw_in(self, event):
        """Handle a RawEvent and generate a kytos/core.messages.in.* event.

        Args:
            event (KytosEvent): RawEvent with openflow message to be unpacked
        """
        self.handle_raw_in(event)

    def handle_raw_in(self, event):
        """Handle a RawEvent and generate a kytos/core.messages.in.* event."""
        # If the switch is already known to the controller, update the
        # 'lastseen' attribute
        switch = event.source.switch
        if switch:
            switch.update_lastseen()

        connection = event.source
        if connection.id not in self._connection_lock:
            self._connection_lock[connection.id] = Lock()

        with self._connection_lock[connection.id]:
            data = connection.remaining_data + event.content['new_data']
            packets, connection.remaining_data = of_slicer(data)
            if not packets:
                return

            unprocessed_packets = []
            multipart_messages = {}

            for packet in packets:
                if not connection.is_alive():
                    return

                if connection.is_new():
                    if not self.process_new_connection(connection, packet):
                        return
                    continue

                try:
                    message = connection.protocol.unpack(packet)
                    if message.header.message_type == Type.OFPT_ERROR:
                        log.error(f"OFPT_ERROR: type {message.error_type},"
                                  f" error code {message.code},"
                                  f" from switch {switch.id},"
                                  f" xid {message.header.xid}/"
                                  f"{message.header.xid:x}")
                except (UnpackException, AttributeError) as err:
                    log.error(err)
                    if isinstance(err, AttributeError):
                        log.error(f'Connection {connection.id}: connection'
                                  f'closed before version negotiation')
                    connection.close()
                    return

                log.debug('Connection %s: IN OFP, ver: %s, type: %s, xid: %s',
                          connection.id,
                          message.header.version,
                          message.header.message_type,
                          message.header.xid)

                ofp_msg_type_str = message.header.message_type.name.lower()
                waiting_features_reply = (
                    ofp_msg_type_str == 'ofpt_features_reply'
                    and connection.protocol.state == 'waiting_features_reply')

                if connection.is_during_setup() and not waiting_features_reply:
                    unprocessed_packets.append(packet)
                    continue

                if ofp_msg_type_str == 'ofpt_multipart_reply':
                    multipart_messages.setdefault(int(message.header.xid), [])
                    multipart_messages[int(message.header.xid)].append(message)
                    continue

                self.emit_message_in(connection, message)

            connection.remaining_data = b''.join(unprocessed_packets) + \
                                        connection.remaining_data

        self.process_multipart_messages(connection, multipart_messages)

    def process_new_connection(self, connection, packet):
        """Process a packet from a new connection."""
        try:
            message = GenericHello(packet=packet)
            self._negotiate(connection, message)
        except (UnpackException, NegotiationException) as err:
            if isinstance(err, UnpackException):
                log.error('Connection %s: Invalid hello message',
                          connection.id)
            else:
                log.error('Connection %s: Negotiation Failed',
                          connection.id)
            connection.protocol.state = 'hello_failed'
            connection.close()
            connection.state = ConnectionState.FAILED
            return False
        connection.set_setup_state()
        return True

    def process_multipart_messages(self, connection, messages):
        """Update the multipart reply counter and emit KytosEvent."""
        switch = connection.switch
        for xid, msgs in messages.items():
            if xid in self._multipart_replies_xids.get(switch.id, {}):
                with self._multipart_replies_xids_lock[switch.id]:
                    self._multipart_replies_xids[switch.id][xid] += len(msgs)
            for message in msgs:
                self.emit_message_in(connection, message)

    def emit_message_in(self, connection, message):
        """Emit a KytosEvent for each incoming message.

        Also update links and port status.
        """
        if not connection.is_alive():
            return
        emit_message_in(self.controller, connection, message)
        msg_type = message.header.message_type.name.lower()
        if msg_type == 'ofpt_port_status':
            self.update_port_status(message, connection)
        elif msg_type == 'ofpt_packet_in':
            self.update_links(message, connection)

    def emit_message_out(self, connection, message):
        """Emit a KytosEvent for each outgoing message."""
        if connection.is_alive():
            emit_message_out(self.controller, connection, message)

    @listen_to('kytos/of_core.v0x0[14].messages.in.ofpt_echo_request')
    def on_echo_request(self, event):
        """Handle Echo Request Messages.

        This method will get a echo request sent by client and generate a
        echo reply as answer.

        Args:
            event (:class:`~kytos.core.events.KytosEvent`):
                Event with echo request in message.

        """
        self.handle_echo_request(event)

    def handle_echo_request(self, event):
        """Handle Echo Request Messages."""
        pyof_lib = PYOF_VERSION_LIBS[event.source.protocol.version]
        echo_request = event.message
        echo_reply = pyof_lib.symmetric.echo_reply.EchoReply(
            xid=echo_request.header.xid,
            data=echo_request.data)
        self.emit_message_out(event.source, echo_reply)

    def _negotiate(self, connection, message):
        """Handle hello messages.

        This method will handle the incoming hello message by client
        and deal with negotiation.

        Parameters:
            event (KytosMessageInHello): KytosMessageInHelloEvent

        """
        if message.versions:
            version = _get_version_from_bitmask(message.versions)
        else:
            version = _get_version_from_header(message.header.version)

        log.debug('connection %s: negotiated version - %s',
                  connection.id, str(version))

        if version is None:
            self.fail_negotiation(connection, message)
            raise NegotiationException()

        version_utils = self.of_core_version_utils[version]
        version_utils.say_hello(self.controller, connection)

        connection.protocol.name = 'openflow'
        connection.protocol.version = version
        connection.protocol.unpack = unpack
        connection.protocol.state = 'sending_features'
        self.send_features_request(connection)
        log.debug('Connection %s: Hello complete', connection.id)

    def fail_negotiation(self, connection, hello_message):
        """Send Error message and emit event upon negotiation failure."""
        log.warning('connection %s: version negotiation failed',
                    connection.id)
        connection.protocol.state = 'hello_failed'
        event_raw = KytosEvent(
            name='kytos/of_core.hello_failed',
            content={'source': connection})
        self.controller.buffers.app.put(event_raw)

        version = max(settings.OPENFLOW_VERSIONS)
        pyof_lib = PYOF_VERSION_LIBS[version]

        error_message = pyof_lib.asynchronous.error_msg.ErrorMsg(
            xid=hello_message.header.xid,
            error_type=pyof_lib.asynchronous.error_msg.
            ErrorType.OFPET_HELLO_FAILED,
            code=pyof_lib.asynchronous.error_msg.HelloFailedCode.
            OFPHFC_INCOMPATIBLE)
        self.emit_message_out(connection, error_message)

    # May be removed
    @listen_to('kytos/of_core.v0x0[14].messages.out.ofpt_echo_reply')
    def on_queued_openflow_echo_reply(self, event):
        """Handle queued OpenFlow echo reply messages."""
        self.handle_queued_openflow_echo_reply(event)

    def handle_queued_openflow_echo_reply(self, event):
        """Handle queued OpenFlow echo reply messages.

        Send a feature request message if SEND_FEATURES_REQUEST_ON_ECHO
        is True (default is False).
        """
        if settings.SEND_FEATURES_REQUEST_ON_ECHO:
            self.send_features_request(event.destination)

    def send_features_request(self, destination):
        """Send a feature request to the switch."""
        version = destination.protocol.version
        pyof_lib = PYOF_VERSION_LIBS[version]
        features_request = pyof_lib.controller2switch.\
            features_request.FeaturesRequest()
        self.emit_message_out(destination, features_request)

    @listen_to('kytos/of_core.v0x0[14].messages.out.ofpt_features_request')
    def on_features_request_sent(self, event):
        """Ensure request has actually been sent before changing state."""
        self.handle_features_request_sent(event)

    @classmethod
    def handle_features_request_sent(cls, event):
        """Ensure request has actually been sent before changing state."""
        if event.destination.protocol.state == 'sending_features':
            event.destination.protocol.state = 'waiting_features_reply'

    @listen_to('kytos/of_core.v0x[0-9a-f]{2}.messages.in.hello_failed',
               'kytos/of_core.v0x0[14].messages.out.hello_failed')
    def on_openflow_in_hello_failed(self, event):
        """Close the connection upon hello failure."""
        self.handle_openflow_in_hello_failed(event)

    @classmethod
    def handle_openflow_in_hello_failed(cls, event):
        """Close the connection upon hello failure."""
        event.destination.close()
        log.debug("Connection %s: Connection closed.", event.destination.id)

    def shutdown(self):
        """End of the application."""
        log.debug('Shutting down...')

    def update_links(self, message, source):
        """Dispatch 'reacheable.mac' event.

        Args:
            message: python openflow (pyof) PacketIn object.
            source: kytos.core.switch.Connection instance.

        Dispatch:
            `reachable.mac`:
                {
                  switch : <switch.id>,
                  port: <port.port_no>
                  reachable_mac: <mac_address>
                }

        """
        ethernet = Ethernet()
        ethernet.unpack(message.data.value)
        if ethernet.ether_type in (EtherType.LLDP, EtherType.IPV6):
            return

        try:
            port = source.switch.get_interface_by_port_no(
                message.in_port.value)
        except AttributeError:
            port = source.switch.get_interface_by_port_no(message.in_port)

        name = 'kytos/of_core.reachable.mac'
        content = {'switch': source.switch,
                   'port': port,
                   'reachable_mac': ethernet.source.value}
        event = KytosEvent(name, content)
        self.controller.buffers.app.put(event)

        msg = 'The MAC %s is reachable from switch/port %s/%s.'
        log.debug(msg, ethernet.source, source.switch.id,
                  message.in_port)

    def _send_specific_port_mod(self, port, interface, current_state):
        """Dispatch port link_up/link_down events."""
        event_name = 'kytos/of_core.switch.interface.'
        event_content = {'interface': interface}

        if port.state.value % 2:
            status = 'link_down'
        else:
            status = 'link_up'

        if current_state:
            if current_state % 2:
                current_status = 'link_down'
            else:
                current_status = 'link_up'
        else:
            current_status = None

        if status != current_status:
            event = KytosEvent(name=event_name+status, content=event_content)
            self.controller.buffers.app.put(event)

    def update_port_status(self, port_status, source):
        """Dispatch 'port.*' events.

        Current events:

        created|deleted|link_up|link_down|modified

        Args:
            port_status: python openflow (pyof) PortStatus object.
            source: kytos.core.switch.Connection instance.

        Dispatch:
            `kytos/of_core.switch.port.[created|modified|deleted]`:
                {
                  switch : <switch.id>,
                  port: <port.port_no>
                  port_description: {<description of the port>}
                }

        """
        reason = port_status.reason.enum_ref(port_status.reason.value).name
        port = port_status.desc
        port_no = port.port_no.value
        event_name = 'kytos/of_core.switch.interface.'

        if reason == 'OFPPR_ADD':
            status = 'created'
            interface = Interface(name=port.name.value,
                                  address=port.hw_addr.value,
                                  port_number=port_no,
                                  switch=source.switch,
                                  state=port.state.value,
                                  features=port.curr)
            source.switch.update_interface(interface)

        elif reason == 'OFPPR_MODIFY':
            status = 'modified'
            interface = source.switch.get_interface_by_port_no(port_no)
            current_status = None
            if interface:
                log.info('Modified %s %s:%s' %
                         (interface, interface.switch.dpid,
                          interface.port_number))
                current_status = interface.state
                interface.state = port.state.value
                interface.name = port.name.value
                interface.address = port.hw_addr.value
                interface.features = port.curr
            else:
                interface = Interface(name=port.name.value,
                                      address=port.hw_addr.value,
                                      port_number=port_no,
                                      switch=source.switch,
                                      state=port.state.value,
                                      features=port.curr)
            source.switch.update_interface(interface)
            self._send_specific_port_mod(port, interface, current_status)

        elif reason == 'OFPPR_DELETE':
            status = 'deleted'
            interface = source.switch.get_interface_by_port_no(port_no)
            interface.deactivate()

        event_name += status
        content = {'interface': interface}

        event = KytosEvent(name=event_name, content=content)
        self.controller.buffers.app.put(event)

        msg = 'The port %s from switch %s was %s.'
        log.debug(msg, port_status.desc.port_no, source.switch.id, status)


def _get_version_from_bitmask(message_versions):
    """Get common version from hello message version bitmap."""
    try:
        return max([version for version in message_versions
                    if version in settings.OPENFLOW_VERSIONS])
    except ValueError:
        return None


def _get_version_from_header(message_version):
    """Get common version from hello message header version."""
    version = min(message_version, max(settings.OPENFLOW_VERSIONS))
    return version if version in settings.OPENFLOW_VERSIONS else None
