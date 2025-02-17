#########
Changelog
#########
All notable changes to the of_core NApp will be documented in this file.

[UNRELEASED] - Under development
********************************

Added
=====
- Added new KytosEvent ``kytos/of_core.switch.interfaces.created`` meant for bulk updates or insertions.

Changed
=======

Deprecated
==========

Removed
=======

Fixed
=====

Security
========

[2022.1.1] - 2022-02-03
***********************

Changed
=======
- Added ``switch.update_lastseen()`` on handle_features_reply


[1.7.0] - 2022-01-04
********************

Changed
=======
- Changed ``update_port_status`` on ``OFPPR_DELETE`` to deactivate an interface instead of deleting it to keep the same object reference that ``topology`` uses when managing the status of a link.

[1.6.1] - 2021-05-26
********************

Added
=====
- New event ``kytos/of_core.flow_stats.received`` to notify when new flow
  statistics are available.
- Added a custom JSON encoder for OF 1.0 flow representation, solving the
  JSON UBInt serialization error.
- Added new event ``switch.interface.created`` in ``handle_port_desc`` to
  notify when a new interface is created.


[1.6.0] - 2021-04-22
********************

Added
=====
- Added class ``ActionSetQueue`` for OpenFlow 1.3.

Changed
=======
- Improved OFPT_ERROR log message adding ``dpid`` and ``xid`` info.

Fixed
=====
- Fixed the string formatting in OFPT_ERROR log message.
- Updated the default ``table_id`` value in the ``FlowBase`` class to
  fix an error in the consistency check.

[1.5.1] - 2020-12-23
********************

Added
=====
- Added support for requesting port statistics.
- Implemented ``FlowBase.__eq__`` to allow direct comparison
  between two flows

Changed
=======
- Changed ``setup.py`` to alert when a test fails on Travis.
- Changed the behavior of the ``handle_port_desc`` method,
  defining the ``OFPPC_NO_FWD`` flag on interfaces that Kytos
  should not send packets to.

Removed
=======
- Removed debug messages with raw OpenFlow packets


[1.5] - 2020-07-23
******************

Added
=====
- Added new fields for OpenFlow 1.3, including SCTP source/destination,
  ARP SPA/TPA/SHA/THA, IPv6 source/destination, MPLS label/TC/BOS,
  Metadata and Tunnel ID match fields.
- Added new unit tests.

Changed
=======
- Updated .coveragerc to ignore .eggs in tests.

Fixed
=====
- Fixed the ``handle_port_desc`` method. Now ``Interface`` instances are
  created using the speed attribute.


[1.4.1] - 2020-05-19
********************

Added
=====
- Added new unit tests, increasing coverage to 47%.
- Added '.travis.yml' to enable Travis CI.
- Added tags decorator to run tests by type and size.

[1.4.0] - 2020-03-09
********************

Changed
=======
- Changed default value for the flow priority to ``0x8000``
  (215, the default was 0). Now it is a value in the
  middle of ``range(0, 2**16)``.
- Changed README.rst to include some info badges.

Fixed
=====
- Fixed some error message log levels from DEBUG to ERROR.
- Fixed Scrutinizer coverage error.
- Fixed __init__.py file in tests folder to solve bug when running tests.


[1.3.2] - 2019-12-20
********************

Changed
=======
- Changed log level of error messages from debug to error.

[1.3.1] - 2019-04-26
******************

Fixed
=======
- Fixed broken API error on flow module.

[1.3] - 2019-03-15
********************
Added
=====
- Added OF_ERROR messages on log files
- Added cookie_mask field on v0x4 version of OpenFlow.

Changed
=======
- Enabled continuous integration on Scrutinizer.
- Updated requirements.
- Updated README.
- Now, a new interface instance will only be created if the interface does not
  exists
- Updated NApp installation.

Removed
=======
- Removed unnecessary events.
- Removed unused dependencies.
- Removed operational status notification.

Fixed
=====
- Fixed some linter errors.
- Fixed interface up.down events, removing unnecessary events. Fix #33

[1.2.0] - 2018-04-20
********************
Added
=====
- Added kytos/of_core.handshake_completed event.
- Add specific events for port and link up/down.
- Add Abstract actions in V0x04.
- Send kytos/of_core.switch.port.created using v0x04.
- Add statistics and instructions support for OF 1.3.
- Add PortStats for OF 1.0.
- Added v0x04 flow support.
- Generate port Created event.
- Add update_flow_list for v0x04.
- Added method to update interfaces for OF1.3 switches.
- Added changelog for of_core NApp.
- Answer Hello with the same version as the switch's.
- Send SetConfig to datapath right after the handshake.
- Send Echo Requests to datapath periodically.
- Adding dependencies in kytos.json.
- Make unpack get lib version from message header.
- Support more pyof libs versions and emmit version specific events.

Changed
=======
- Improvements for the OpenFlow 1.3 Handshake.
- Moved Interface import.
- Adapt the NApp to changes in python-openflow.
- Avoid wrong NApp naming.
- Deal with PortStatus the proper way.
- Deal with multiple flow stats multipart replies.
- Return proper Flow class for a switch.
- Save generic flow for OF 1.3 in controller.switch.
- Also store OF 1.3 flows in controller switch.flows.
- Refactoring: reuse base flow in OF 1.0.
- Improve reachable.mac event content.
- Moved flow.py module to the of_core NApp.
- Change 'not implemented' log INFO to ERROR.
- Change import statement.
- Connection state handling improvement.
- Change fetch_latest to avoid UnboundLocalError.
- Connection state check improvement.
- Update docstrings, logs and comments.
- Handshake intermediary update. New version negotiation. Once version is decided, it will now need to send features_request or hello_failed error_message with the correct version.
- Update of_core utils with a few methods/classes - emit_message_in - emit_message_out - GenericHello - NegotiationException.
- Use switch.id in flow.id.

Removed
=======
- Exclude Match fields with None value from JSON.
- Remove nw_tos.
- Remove JSON example from of_topology README.
- Remove unpack from kytos/of_core/utils.py.
- Removed self.versions from kytos/of_core.

Fixed
=====
- Fix 'reachable' event for OF1.3 packets.
- Fix catch interface modified/deleted.
- Fix converting python-openflow actions.
- Fix flow.switch serialization.
- Fix version-dependent classes in Flow abstract cls.
- Fix different Flow ID after restarting controller.
- Fix error while getting PortStatus Reason.
- Fix import from Kytos Connection module.
- Fix OpenFlow Hello messages in of_core.
- A few napps fixes to check for switch connection version before acting.

Security
========
- Some bug fixes.

[1.1.0] - 2017-06-16
********************
Added
=====
- New request handler alters of_core so that all message parsing and processing happens outside the core tcp_server
- Call 'update_lastseen' when OF message arrives
- Include data field from echo request in echo reply.
