# Data Plane Explanation

## Overview

The P4 program `p4_bareflow.p4` implements an L2 learning bridge on a Barefoot Tofino switch, defining the data plane that processes packets in real time at line rate. It uses P4 to specify packet parsing, table lookups, forwarding actions, and metadata handling. The data plane handles Ethernet packets with logic for dynamic MAC learning, unicast/multicast forwarding, flooding, and communication with the CPU for control decisions.

### Main Data Plane Processes

1. **Packet Parsing and Classification**:
   - Extracts Ethernet headers and intrinsic switch metadata.
   - Classifies packets by origin: normal, resubmitted (second pass), or from the CPU.
   - Initializes metadata for lookups and forwarding decisions.

2. **First Pass (Initial Ingress)**:
   - Examines the source MAC for learning.
   - Looks up `mac_state` to check whether the MAC is known.
   - If unknown or a move is detected, sends the packet to the CPU for learning.
   - If valid, marks the packet for resubmission and proceeds to the second pass.

3. **Second Pass (Resubmit)**:
   - Uses the original timestamp and port from the resubmit header.
   - Examines the destination MAC.
   - If known and valid, forwards by unicast to the learned port.
   - If unknown or a multicast group, starts flooding.
   - Handles aging: removes expired entries and notifies the CPU.

4. **Forwarding and Output Actions**:
   - Unicast: Sends the packet to a specific port.
   - Multicast/Flooding: Uses the PRE to replicate to multiple ports.
   - CPU: Encapsulates and sends to the CPU port for control processing.

5. **Register and Timestamp Management**:
   - The `mac_state_tstamp` and `mac_state_valid` registers store per-entry state.
   - Register actions check validity and update timestamps.
   - Implement blocking and aging policies.

6. **Controller Interaction**:
   - Sends packets to the CPU for learning or expiration events.
   - Receives controller responses for direct forwarding.
   - Synchronizes state between the data plane and control plane.

7. **Packet Replication Engine (PRE)**:
   - Configured with multicast groups for flooding.
   - Excludes the source port during flooding to prevent loops.

The data plane provides deterministic, high-performance operation, delegating complex decisions to the controller while handling basic packet forwarding.

## Data Structures

### Headers

- **`ethernet_t`**: Standard Ethernet header with destination/source MAC addresses and EtherType.
- **`resubmit_md_t`**: Resubmit header containing the original timestamp and ingress port.
- **`cpu_header_t`**: Header for CPU-switch communication, including an operation code and forwarding port.

### Metadata

The `metadata_t` structure includes fields for:

- MAC lookups: `lookup_mac`, `lookup_hit`, `lookup_port`, etc.
- Timestamps and validation: `lookup_time_result`, `lookup_valid`, `valid_invalidate`.
- State flags: `is_second_pass`, `flood_src_port`.
- CPU communication: `cpu_redirect_code`, `cpu_redirect_original_port`.
- Other fields: `ts32` (timestamp), `reg_dir` (register index).

## Ingress Parser

`SwitchIngressParser` parses incoming packets:

- **`start` state**: Initializes metadata and extracts `ingress_intrinsic_metadata_t`.
- Chooses the next state based on `resubmit_flag` and `ingress_port`:
  - If resubmitted: `parse_resubmit`.
  - If from the CPU (port 64): `parse_cpu`.
  - Default: `skip_port_metadata`.
- **Parse resubmit**: Extracts the resubmit header.
- **Parse CPU**: Extracts the CPU header.
- **Parse Ethernet**: Extracts the Ethernet header.

## Ingress Control

`SwitchIngress` is the processing core:

### Constants

- `BLOCK_TIME_CTE`: Blocking time to prevent MAC moves (2 seconds).
- `ENTRY_MAX_AGE_CTE`: Maximum entry lifetime (120 seconds).
- `CPU_ETHERNET_PORT`: CPU port (64).
- CPU operation codes.

### Registers

- `mac_state_tstamp`: MAC entry timestamps (65536 entries).
- `mac_state_valid`: Validity flags (65536 entries).

### Register Actions

- `valid_access`: Checks and optionally invalidates entries.
- `tstamp_first_pass`: Handles timestamps in the first pass (learning).
- `tstamp_second_pass`: Handles timestamps in the second pass (forwarding).

### Table Actions

- `mac_hit`: Marks a lookup hit and sets the port and register.
- `mac_miss`: Marks a miss and resets fields.
- `drop`: Drops the packet.
- `set_unicast`: Sets the unicast output port.
- `set_flood_grp`: Sets the multicast group for flooding.

### Tables

- **`mac_state`**: Destination/source MAC lookup. Key: `lookup_mac`. Actions: `mac_hit`, `mac_miss`.
- **`flood_by_ingress`**: Maps the ingress port to a flooding group. Key: `flood_src_port`. Action: `set_flood_grp`.

### Apply Logic

The logic is split into three main paths:

#### 1. Packets from the CPU

- Reads the code and forward fields from the CPU header.
- Invalidates the CPU header.
- Depending on the code:
  - `UNICAST`: Forwards to a specific port.
  - `MULTICAST`: Floods using a group based on the original port.
  - Default: Drop.

#### 2. First Pass (Without Resubmit)

- Sets `is_second_pass = 0` and the current timestamp.
- Looks up the source MAC in `mac_state`.
- On a miss: Sends to the CPU for learning.
- On a hit:
  - Checks whether the port matches.
  - Handles blocking and aging.
  - If the port does not match and the entry is unlocked: Invalidates it and sends to the CPU.
  - If the port matches: Marks for resubmission.

#### 3. Second Pass (With Resubmit)

- Sets `is_second_pass = 1` and the original timestamp.
- If the destination MAC is a group address (bit 40 = 1): Floods.
- Otherwise: Looks up the destination MAC.
- On a miss: Floods.
- On a hit:
  - Checks aging.
  - If aged: Invalidates the entry and sends to the CPU.
  - If valid: Forwards by unicast.

### Final Actions

- `pkt_action = 0`: Drop.
- `pkt_action = 1`: Resubmit.
- `pkt_action = 2`: Unicast.
- `pkt_action = 3`: Flood.
- `pkt_action = 4`: Send to CPU.

## Ingress Deparser

`SwitchIngressDeparser`:

- If resubmitting: Emits a resubmit header with the timestamp and original port.
- Emits CPU and Ethernet headers.

## Egress

Egress is minimal: the parser extracts metadata, and the control and deparser are empty. No additional processing takes place in egress.

## Complete Pipeline

The pipeline combines the ingress parser, ingress control, ingress deparser, egress parser, egress control, and egress deparser.
