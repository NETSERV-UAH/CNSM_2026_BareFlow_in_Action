# Controller

## Overview

The Python controller (`main.py`) manages the P4-Bareflow switch's control plane, making decisions based on data plane events. It uses the BF-RT (Barefoot Runtime) API over gRPC to dynamically configure the Tofino switch's tables, registers, and ports. Its main role is to implement control policies that the data plane cannot handle efficiently, such as MAC address learning, aging management, multicast flooding configuration, and bidirectional communication with the data plane.

### Main Control Processes

1. **System Initialization**:
   - Establishes a gRPC connection to the switch.
   - Configures physical ports (speed, FEC, auto-negotiation).
   - Initializes the Packet Replication Engine (PRE) for multicast flooding.
   - Configures forwarding tables and state registers.

2. **MAC Address Learning**:
   - Receives learning packets from the data plane when an unknown MAC arrives.
   - Checks whether the MAC already exists in the software database.
   - If new, allocates a register index, adds an entry to `mac_state`, and updates the timestamp and validity registers.
   - Handles MAC moves (when a MAC appears on a different port).

3. **Aging Management**:
   - Monitors MAC entry timestamps.
   - Receives data plane notifications when an entry expires.
   - Removes obsolete table entries and frees register resources.

4. **Flooding Configuration**:
   - Creates multicast groups for flooding based on the source port.
   - Adds replication nodes to the PRE to exclude the source port during flooding.

5. **Bidirectional CPU-Data Plane Communication**:
   - Listens on a Unix socket for packets from the data plane.
   - Processes operation codes (learn, aged) and takes the corresponding actions.
   - Sends responses to the data plane for unicast or multicast forwarding.

6. **Monitoring and Debugging**:
   - Periodically dumps the MAC table for inspection.
   - Logs events and errors for troubleshooting.
   - Validates consistency between the software database and hardware.

7. **Cleanup and Shutdown**:
   - Handles termination signals (SIGINT, SIGTERM).
   - Clears all table entries and registers.
   - Closes connections and frees resources.

The controller maintains a software database synchronized with hardware state, ensuring consistent and efficient forwarding decisions. It responds reactively to data plane events and proactively through periodic tasks.

## Dependencies and Imports

- **Standard libraries**: `sys`, `os`, `time`, `signal`, `socket`, `select`, `logging`, `collections.deque`.
- **BF-RT**: `bfrt_grpc.client` for switch interaction.
- **Helper modules**: `grpc_pm`, `grpc_commons`, `grpc_tables`, `grpc_regs`, `grpc_pre`, `auxiliars`.

## Initial Configuration

### Environment Variables

- `GRPC_HOST`, `GRPC_PORT`: BF-RT server address.
- `CLIENT_ID`, `DEVICE_ID`: Connection identifiers.
- `CPU_IFACE`: Linux interface for the CPU port.
- `LOG_LEVEL`: Logging level.

### Constants

- `HOSTS_BRIDGE_PORTS`: Host ports (44-47).
- `PORT_CONFIGS`: Port settings (speed, FEC, etc.).
- `BASE_MGID`, `BASE_NODE_ID`: Base values for multicast groups and PRE nodes.
- `REG_ARRAY_SIZE`: Register array size (65536).
- `MAC_DUMP_INTERVAL_SECS`: MAC table dump interval.
- CPU-data plane operation codes.

### Software Database

- `mac_db`: Dictionary mapping each MAC to its port, register index, and validity.
- `free_reg_indices`: Queue of free register indices.

## Connection and Object Retrieval

- Connects to BF-RT using `connect_bfrt`.
- Retrieves table objects: `mac_state`, `flood_by_ingress`, and the `mac_state_tstamp` and `mac_state_valid` registers.
- Retrieves PRE tables: `$pre.node`, `$pre.mgid`.
- Retrieves the port table: `$PORT`.

## Helper Functions

- `mgid_for_ingress_port(port)`: Calculates the MGID for a port.
- `node_id_for_ingress_port(port)`: Calculates the node ID for a port.
- `alloc_reg_index()`: Allocates a free register index.
- `free_reg_index(index)`: Frees a register index.

## Register Management

- `discover_controller_register_fields()`: Discovers register field names.
- `set_tstamp_slot(reg_index, ts32)`: Writes a timestamp to a register.
- `set_valid_slot(reg_index, valid)`: Writes validity to a register.
- `read_tstamp_slot(reg_index)`: Reads a timestamp.
- `read_valid_slot(reg_index)`: Reads validity.
- `clear_register_slot(reg_index)`: Clears a register slot.

## Table Management

- `wait_until_mac_state_present()`: Waits until a MAC entry is present in hardware.
- `clear_pre_entries()`: Clears PRE entries.
- `clear_program_tables()`: Clears program tables.
- `add_mac_state_entry(mac, port, reg_dir)`: Adds an entry to `mac_state`.
- `delete_mac_state_entry(mac)`: Deletes an entry from `mac_state`.
- `add_flood_entry(port, mgid)`: Adds an entry to `flood_by_ingress`.

## PRE (Packet Replication Engine) Configuration

- `add_replication_node(port, node_id)`: Adds a replication node.
- `add_multicast_group(mgid, ports)`: Adds a multicast group.

## Port Initialization

- `initialize_ports()`: Configures ports according to `PORT_CONFIGS`.

## MAC Learning

- Detects learning packets from the data plane.
- Adds entries to `mac_db`, tables, and registers.
- Handles MAC moves (port changes).

## CPU Communication

- Listens on a Unix socket for packets from the data plane.
- Processes codes: `LEARN` (learning), `AGED` (removal due to age).
- Sends responses to the data plane through the socket.

## Main Loop

- Initializes ports and the PRE.
- Configures flooding tables.
- In the loop:
  - Receives CPU packets.
  - Processes learning/aged events.
  - Periodically dumps the MAC table.
  - Handles signals for cleanup.

## Cleanup and Signals

- `signal_handler()`: Handles SIGINT/SIGTERM for cleanup.
- Clears tables and registers and closes connections.
