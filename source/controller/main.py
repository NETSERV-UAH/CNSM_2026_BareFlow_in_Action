#!/usr/bin/env python3
import sys
import os
import time
import signal
import socket
import select
import logging
from collections import deque

sys.path.append(os.path.expandvars('$SDE/install/lib/python3.8/site-packages/tofino/'))
sys.path.append(os.path.expandvars('$SDE/install/lib/python3.8/site-packages/'))
sys.path.append(os.path.expandvars('$SDE/install/lib/python3.8/site-packages/bf_ptf/'))
sys.path.append(os.path.expandvars('/home/arppath/tofino-quick-start/test/p4-bareflow/tofino-libs'))

import bfrt_grpc.client as gc

from grpc_pm import initialize_ports
from grpc_commons import connect_bfrt
from grpc_tables import extract_table_obj, dump_table
from grpc_auxiliars import mac_to_int, int_to_mac

from pre_conf import clear_pre_entries, program_flood_groups
from pktgen_conf import program_pktgen_port_down, disable_all_pktgen_apps, connect_conn_mgr, close_conn_mgr, arm_pktgen_port_down_ports
from mac_table_mgmt import discover_mac_register_fields, clear_mac_tables, read_tstamp_slot, read_valid_slot, get_mac_table_rows_with_registers, install_or_update_source_mac as mac_table_install_or_update_source_mac, remove_mac as mac_table_remove_mac, resolve_destination, source_mac_move_allowed
from port_state_mgmt import clear_port_status_table, create_sync_port_status_from_hw, sync_port_status_from_hw, modify_port_status_entry


# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(message)s"
)

logger = logging.getLogger("bareflow-controller")


# BF-RT gRPC server address
GRPC_ADDR = f'{os.getenv("GRPC_HOST", "localhost")}:{os.getenv("GRPC_PORT", "50052")}'
CLIENT_ID = int(os.getenv("CLIENT_ID", "0"))
DEVICE_ID = int(os.getenv("DEVICE_ID", "0"))
PIPE_ID = int(os.getenv("PIPE_ID", "0xffff"), 16)

# Linux interface connected to the switch CPU Ethernet port
CPU_IFACE = os.getenv("CPU_IFACE", "enp4s0f0")

# Host ports
HOSTS_BRIDGE_PORTS = [44, 45, 46, 47]

PORT_CONFIGS = [
    {
        "dev_port": 44,
        "speed": "BF_SPEED_10G",
        "fec": "BF_FEC_TYP_NONE",
        "n_lanes": 1,
        "auto_negotiation": "PM_AN_FORCE_DISABLE",
    },
    {
        "dev_port": 45,
        "speed": "BF_SPEED_10G",
        "fec": "BF_FEC_TYP_NONE",
        "n_lanes": 1,
        "auto_negotiation": "PM_AN_FORCE_DISABLE",
    },
    {
        "dev_port": 46,
        "speed": "BF_SPEED_10G",
        "fec": "BF_FEC_TYP_NONE",
        "n_lanes": 1,
        "auto_negotiation": "PM_AN_FORCE_DISABLE",
    },
    {
        "dev_port": 47,
        "speed": "BF_SPEED_10G",
        "fec": "BF_FEC_TYP_NONE",
        "n_lanes": 1,
        "auto_negotiation": "PM_AN_FORCE_DISABLE",
    },
    {
        "dev_port": 64,
        "speed": "BF_SPEED_10G",
        "fec": "BF_FEC_TYP_NONE",
        "n_lanes": 1,
        "auto_negotiation": "PM_AN_DEFAULT",
    }
]

# PRE ranges
BASE_MGID = 1000
BASE_NODE_ID = 2000

# P4 register array size
REG_ARRAY_SIZE = 65536

# Periodic dump interval
MAC_DUMP_INTERVAL_SECS = 5.0

# Maximum wait to confirm an entry is present in hardware
MAC_STATE_INSTALL_TIMEOUT_SECS = 1.0
MAC_STATE_INSTALL_POLL_SECS = 0.01

# Controller timing policy
BLOCK_TIME_CTE = 30518

# CPU header
CPU_TO_DP_CODE_UNICAST = 0
CPU_TO_DP_CODE_MULTICAST = 1

DP_TO_CPU_CODE_LEARN = 0
DP_TO_CPU_CODE_AGED = 1
DP_TO_CPU_CODE_PORT_DOWN = 2
DP_TO_CPU_CODE_PORT_UNAVAILABLE = 3

CPU_HEADER_LEN = 7

# Packet generator
PKTGEN_SRC_PORT = 68
PKTGEN_PORT_DOWN_APP_ID = 3

# Free register indices
free_reg_indices = deque(range(REG_ARRAY_SIZE))

# Software database:
# mac_int -> {"port": int, "reg_dir": int, "valid": int}
mac_db = {}

running = True

# BF-RT connection
interface, bfrt_info, target = connect_bfrt(GRPC_ADDR, CLIENT_ID, DEVICE_ID, PIPE_ID)
pkt_gen_target = gc.Target(device_id=DEVICE_ID, pipe_id=0)

# Program tables
t_mac_state = extract_table_obj(bfrt_info, "pipe.SwitchIngress.mac_state")
t_port_status = extract_table_obj(bfrt_info, "pipe.SwitchIngress.port_status")
t_flood = extract_table_obj(bfrt_info, "pipe.SwitchIngress.flood_by_ingress")
t_reg_tstamp = extract_table_obj(bfrt_info, "pipe.SwitchIngress.mac_state_tstamp")
t_reg_valid = extract_table_obj(bfrt_info, "pipe.SwitchIngress.mac_state_valid")

# PRE
t_pre_node = extract_table_obj(bfrt_info, "$pre.node")
t_pre_mgid = extract_table_obj(bfrt_info, "$pre.mgid")

# Port table
t_port = extract_table_obj(bfrt_info, "$PORT")

# Packet generator configuration tables
t_pktgen_app_cfg = extract_table_obj(bfrt_info, "tf1.pktgen.app_cfg")
t_pktgen_port_cfg = extract_table_obj(bfrt_info, "tf1.pktgen.port_cfg")

# Actual register fields
REG_TSTAMP_FIELD = None
REG_VALID_FIELD = None

cpu_sock = None
conn_mgr_client = None
conn_mgr_transport = None
conn_mgr_sess_hdl = None


def discover_controller_register_fields():
    global REG_TSTAMP_FIELD, REG_VALID_FIELD

    REG_TSTAMP_FIELD, REG_VALID_FIELD = discover_mac_register_fields(t_reg_tstamp=t_reg_tstamp, t_reg_valid=t_reg_valid, target=target)


def clear_program_tables():
    clear_mac_tables(target=target, t_mac_state=t_mac_state, t_flood=t_flood)


def controller_read_tstamp_slot(reg_index):
    try:
        return read_tstamp_slot(t_reg_tstamp=t_reg_tstamp, target=target, reg_tstamp_field=REG_TSTAMP_FIELD, reg_index=reg_index)
    except Exception as e:
        logger.warning("Could not read mac_state_tstamp[%s] -> %s", reg_index, e)

    return None


def controller_read_valid_slot(reg_index):
    try:
        return read_valid_slot(t_reg_valid=t_reg_valid, target=target, reg_valid_field=REG_VALID_FIELD, reg_index=reg_index)
    except Exception as e:
        logger.warning("Could not read mac_state_valid[%s] -> %s", reg_index, e)

    return None


def print_pretty_mac_table_with_registers():
    try:
        mac_rows = get_mac_table_rows_with_registers(
            target=target,
            t_mac_state=t_mac_state,
            t_reg_tstamp=t_reg_tstamp,
            t_reg_valid=t_reg_valid,
            reg_tstamp_field=REG_TSTAMP_FIELD,
            reg_valid_field=REG_VALID_FIELD,
            mac_db=mac_db
        )

    except Exception as e:
        logger.warning("Could not read the mac_state table -> %s", e)
        return

    logger.info("")
    logger.info("=" * 110)
    logger.info("mac_state TABLE - Bareflow")
    logger.info("=" * 110)

    if not mac_rows:
        logger.info("(empty)")
        logger.info("=" * 110)
        logger.info("")
        return

    logger.info(
        f"{'MAC':17}  "
        f"{'PORT':>6}  "
        f"{'REG_DIR':>7}  "
        f"{'TS32':>12}  "
        f"{'VALID_HW':>8}  "
        f"{'VALID_SW':>8}"
    )
    logger.info("-" * 110)

    for row in mac_rows:
        logger.info(
            f"{int_to_mac(row['mac']):17}  "
            f"{str(row['port']):>6}  "
            f"{str(row['reg_dir']):>7}  "
            f"{str(row['ts32']):>12}  "
            f"{str(row['valid_hw']):>8}  "
            f"{str(row['valid_sw']):>8}"
        )

    logger.info("=" * 110)
    logger.info("")


def open_cpu_interface():
    global cpu_sock

    SOL_PACKET = 263
    PACKET_ADD_MEMBERSHIP = 1
    PACKET_MR_PROMISC = 1

    cpu_sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
    cpu_sock.bind((CPU_IFACE, 0))

    ifindex = socket.if_nametoindex(CPU_IFACE)

    mreq = (
        int(ifindex).to_bytes(4, byteorder=sys.byteorder) +
        int(PACKET_MR_PROMISC).to_bytes(2, byteorder=sys.byteorder) +
        int(0).to_bytes(2, byteorder=sys.byteorder) +
        bytes(8)
    )

    cpu_sock.setsockopt(SOL_PACKET, PACKET_ADD_MEMBERSHIP, mreq)
    cpu_sock.setblocking(False)

    logger.info("CPU interface opened on %s in promiscuous mode", CPU_IFACE)


def close_cpu_interface():
    global cpu_sock

    if cpu_sock is not None:
        try:
            cpu_sock.close()
        except Exception:
            pass

        cpu_sock = None


def recv_cpu_packet(timeout=0.1):
    if cpu_sock is None:
        return None

    ready, _, _ = select.select([cpu_sock], [], [], timeout)

    if not ready:
        return None

    data = cpu_sock.recv(65535)

    if not data:
        return None

    return data


def send_cpu_packet(frame_bytes):
    if cpu_sock is None:
        raise RuntimeError("The CPU interface is not open")

    cpu_sock.send(frame_bytes)


def build_cpu_header(code, forward, ts32=0):
    code = int(code) & 0x7
    forward = int(forward) & 0xFFFF
    ts32 = int(ts32) & 0xFFFFFFFF

    b0 = (code << 5) & 0xE0
    b1 = (forward >> 8) & 0xFF
    b2 = forward & 0xFF
    b3 = (ts32 >> 24) & 0xFF
    b4 = (ts32 >> 16) & 0xFF
    b5 = (ts32 >> 8) & 0xFF
    b6 = ts32 & 0xFF

    return bytes([b0, b1, b2, b3, b4, b5, b6])


def parse_cpu_packet(frame):
    if frame is None or len(frame) < CPU_HEADER_LEN:
        return None

    code = (frame[0] >> 5) & 0x7
    forward = (frame[1] << 8) | frame[2]
    ts32 = (
        (frame[3] << 24) |
        (frame[4] << 16) |
        (frame[5] << 8) |
        frame[6]
    )

    if code == DP_TO_CPU_CODE_PORT_DOWN:
        return {
            "code": code,
            "forward": forward,
            "ts32": ts32,
            "down_port": forward,
            "ethernet": b"",
            "dst_mac": None,
            "src_mac": None,
            "ether_type": None,
        }

    if code not in (
        DP_TO_CPU_CODE_LEARN,
        DP_TO_CPU_CODE_AGED,
        DP_TO_CPU_CODE_PORT_UNAVAILABLE,
    ):
        return None

    if len(frame) < CPU_HEADER_LEN + 14:
        return None

    if code == DP_TO_CPU_CODE_LEARN:
        if forward not in HOSTS_BRIDGE_PORTS:
            return None

    if code == DP_TO_CPU_CODE_AGED:
        if forward != 0:
            return None

    if code == DP_TO_CPU_CODE_PORT_UNAVAILABLE:
        if forward not in HOSTS_BRIDGE_PORTS:
            return None

    eth = frame[CPU_HEADER_LEN:]

    if len(eth) < 14:
        return None

    dst_mac = int.from_bytes(eth[0:6], byteorder="big")
    src_mac = int.from_bytes(eth[6:12], byteorder="big")
    ether_type = int.from_bytes(eth[12:14], byteorder="big")

    return {
        "code": code,
        "forward": forward,
        "ts32": ts32,
        "ethernet": eth,
        "dst_mac": dst_mac,
        "src_mac": src_mac,
        "ether_type": ether_type,
    }


def send_back_unicast(ethernet_bytes, out_port):
    frame = build_cpu_header(CPU_TO_DP_CODE_UNICAST, out_port, 0) + ethernet_bytes
    send_cpu_packet(frame)

    logger.info("Reinjecting packet by unicast to port %s", int(out_port))


def send_back_multicast(ethernet_bytes, ingress_port):
    frame = build_cpu_header(CPU_TO_DP_CODE_MULTICAST, ingress_port, 0) + ethernet_bytes
    send_cpu_packet(frame)

    logger.info("Reinjecting packet by multicast using ingress port %s", int(ingress_port))


def controller_install_or_update_source_mac(mac, ingress_port, ts32):
    mac = mac_to_int(mac)
    ingress_port = int(ingress_port)
    ts32 = int(ts32) & 0xFFFFFFFF

    installed, operation, reg_dir, old_port = mac_table_install_or_update_source_mac(
        target=target,
        t_mac_state=t_mac_state,
        t_reg_tstamp=t_reg_tstamp,
        t_reg_valid=t_reg_valid,
        reg_tstamp_field=REG_TSTAMP_FIELD,
        reg_valid_field=REG_VALID_FIELD,
        free_reg_indices=free_reg_indices,
        mac_db=mac_db,
        mac=mac,
        ingress_port=ingress_port,
        ts32=ts32,
        mac_state_install_timeout_secs=MAC_STATE_INSTALL_TIMEOUT_SECS,
        mac_state_install_poll_secs=MAC_STATE_INSTALL_POLL_SECS
    )

    if not installed:
        if operation == "learn":
            logger.warning("Timed out confirming hardware installation of MAC %s on port %s with index %s", int_to_mac(mac), ingress_port, reg_dir)
        else:
            logger.warning("Timed out confirming hardware update of MAC %s to port %s with index %s", int_to_mac(mac), ingress_port, reg_dir)
        return

    if operation == "learn":
        logger.info("Learning MAC %s on port %s using register index %s and ts32 %s", int_to_mac(mac), ingress_port, reg_dir, ts32)
        return

    if operation == "move":
        logger.info("Moving MAC %s from port %s to port %s using register index %s and ts32 %s", int_to_mac(mac), old_port, ingress_port, reg_dir, ts32)
        return

    logger.info("Refreshing MAC %s on port %s using register index %s and ts32 %s", int_to_mac(mac), ingress_port, reg_dir, ts32)


def controller_remove_mac(mac, reason="DELETE"):
    mac = mac_to_int(mac)

    try:
        removed, reg_dir = mac_table_remove_mac(
            target=target,
            t_mac_state=t_mac_state,
            t_reg_tstamp=t_reg_tstamp,
            t_reg_valid=t_reg_valid,
            reg_tstamp_field=REG_TSTAMP_FIELD,
            reg_valid_field=REG_VALID_FIELD,
            free_reg_indices=free_reg_indices,
            reg_array_size=REG_ARRAY_SIZE,
            mac_db=mac_db,
            mac=mac
        )

    except Exception as e:
        logger.warning("Could not delete the mac_state entry for %s -> %s", int_to_mac(mac), e)
        return

    if not removed:
        logger.info("Attempted to delete MAC %s, but it was not in the controller database", int_to_mac(mac))
        return

    logger.info("Removing MAC %s and freeing register index %s Reason: %s", int_to_mac(mac), reg_dir, reason)


def process_port_down_packet(pkt):
    down_port = int(pkt["down_port"])

    if down_port not in HOSTS_BRIDGE_PORTS:
        return

    logger.info("")
    logger.info("[CPU] port_down event: port = %s ts32 = %s", down_port, pkt["ts32"])

    modify_port_status_entry(t_port_status, target, down_port, False)
    logger.info("port_status[%s] = down", down_port)

    try:
        arm_pktgen_port_down_ports(conn_mgr_client=conn_mgr_client, sess_hdl=conn_mgr_sess_hdl, device_id=DEVICE_ID, ports=[down_port])
    except Exception as e:
        logger.warning("Could not rearm the port_down event for port %s -> %s", down_port, e)

def process_port_unavailable_packet(pkt):
    ingress_port = int(pkt["forward"])

    if ingress_port not in HOSTS_BRIDGE_PORTS:
        logger.warning(
            "port_unavailable event with invalid ingress port: %s",
            ingress_port
        )
        return

    logger.info("")
    logger.info(
        "[CPU] port_unavailable event: reflooding using original ingress port = %s ts32 = %s",
        ingress_port,
        pkt["ts32"]
    )

    send_back_multicast(pkt["ethernet"], ingress_port)


def process_learn_like_packet(pkt):
    src_mac = pkt["src_mac"]
    dst_mac = pkt["dst_mac"]
    ingress_port = int(pkt["forward"])
    ts32 = int(pkt["ts32"]) & 0xFFFFFFFF

    logger.info("")
    logger.info(
        "[CPU] First-pass event: src = %s dst = %s ingress_port = %s ts32 = %s",
        int_to_mac(src_mac),
        int_to_mac(dst_mac),
        ingress_port,
        ts32
    )

    if src_mac not in mac_db:
        controller_install_or_update_source_mac(src_mac, ingress_port, ts32)

    else:
        old_port = int(mac_db[src_mac]["port"])

        if ingress_port == old_port:
            controller_install_or_update_source_mac(src_mac, ingress_port, ts32)

        else:
            reg_dir = int(mac_db[src_mac]["reg_dir"])

            try:
                allow_move, valid_hw, tstamp_hw = source_mac_move_allowed(
                    t_reg_tstamp=t_reg_tstamp,
                    t_reg_valid=t_reg_valid,
                    target=target,
                    reg_tstamp_field=REG_TSTAMP_FIELD,
                    reg_valid_field=REG_VALID_FIELD,
                    reg_dir=reg_dir,
                    ts32=ts32,
                    block_time_cte=BLOCK_TIME_CTE
                )

            except Exception as e:
                logger.warning("Could not read hardware state for MAC %s. Dropping the event as a precaution -> %s", int_to_mac(src_mac), e)
                return

            if valid_hw is None or tstamp_hw is None:
                logger.warning("Could not read hardware state for MAC %s. Dropping the event as a precaution.", int_to_mac(src_mac))
                return

            if not allow_move:
                logger.info(
                    "Rejecting the move of MAC %s from port %s to %s because it is still locked "
                    "(valid_hw=%s tstamp_hw=%s ts32=%s)",
                    int_to_mac(src_mac),
                    old_port,
                    ingress_port,
                    int(valid_hw),
                    int(tstamp_hw),
                    int(ts32)
                )
                return

            controller_install_or_update_source_mac(src_mac, ingress_port, ts32)

    dst_mode, dst_port = resolve_destination(mac_db=mac_db, dst_mac=dst_mac)

    if dst_mode == "unicast":
        send_back_unicast(pkt["ethernet"], dst_port)
        return

    send_back_multicast(pkt["ethernet"], ingress_port)


def process_aged_packet(pkt):
    dst_mac = pkt["dst_mac"]
    src_mac = pkt["src_mac"]
    ts32 = int(pkt["ts32"]) & 0xFFFFFFFF

    logger.info("")
    logger.info("[CPU] aged event: src = %s dst = %s ts32 = %s", int_to_mac(src_mac), int_to_mac(dst_mac), ts32)

    controller_remove_mac(dst_mac, reason="envejecimiento detectado en dataplane")

    if src_mac in mac_db and int(mac_db[src_mac].get("valid", 0)) != 0:
        ingress_port = int(mac_db[src_mac]["port"])
        send_back_multicast(pkt["ethernet"], ingress_port)
        return

    logger.warning("Cannot reflood the aged packet because no valid ingress port is known for source MAC %s. Dropping it.", int_to_mac(src_mac))


def process_cpu_packet(pkt):
    code = int(pkt["code"])

    if code == DP_TO_CPU_CODE_LEARN:
        process_learn_like_packet(pkt)
        return

    if code == DP_TO_CPU_CODE_AGED:
        process_aged_packet(pkt)
        return

    if code == DP_TO_CPU_CODE_PORT_DOWN:
        process_port_down_packet(pkt)
        return

    if code == DP_TO_CPU_CODE_PORT_UNAVAILABLE:
        process_port_unavailable_packet(pkt)
        return

    logger.warning("Unknown CPU code received from the data plane: %s", code)


def cleanup():
    logger.info("Starting final cleanup")

    close_cpu_interface()

    try:
        clear_program_tables()
    except Exception as e:
        logger.warning("Could not clear program tables -> %s", e)

    try:
        clear_port_status_table(target, t_port_status)
    except Exception as e:
        logger.warning("Could not clear port_status -> %s", e)

    try:
        clear_pre_entries(target=target, pre_mgid_table=t_pre_mgid, pre_node_table=t_pre_node)
    except Exception as e:
        logger.warning("Could not clear PRE entries -> %s", e)

    try:
        disable_all_pktgen_apps(pkt_gen_target=pkt_gen_target, pktgen_app_cfg_table=t_pktgen_app_cfg)
    except Exception as e:
        logger.warning("Could not disable pktgen apps -> %s", e)

    try:
        close_conn_mgr(conn_mgr_client=conn_mgr_client, transport=conn_mgr_transport, sess_hdl=conn_mgr_sess_hdl)
    except Exception as e:
        logger.warning("Could not close conn_mgr -> %s", e)

    logger.info("Final cleanup complete")


def stop_handler(signum, frame):
    global running
    running = False


signal.signal(signal.SIGINT, stop_handler)
signal.signal(signal.SIGTERM, stop_handler)


def main_loop():
    logger.info("Controller ready and waiting for CPU packets")

    next_dump_ts = time.time() + MAC_DUMP_INTERVAL_SECS

    while running:
        frame = recv_cpu_packet(timeout=0.1)

        if frame is not None:
            try:
                pkt = parse_cpu_packet(frame)

                if pkt is not None:
                    process_cpu_packet(pkt)

            except Exception as e:
                logger.exception("Error processing CPU packet -> %s", e)

        now_ts = time.time()

        if now_ts >= next_dump_ts:
            print_pretty_mac_table_with_registers()
            port_states = sync_port_status_from_hw(t_port, t_port_status, target, HOSTS_BRIDGE_PORTS)
            next_dump_ts = now_ts + MAC_DUMP_INTERVAL_SECS


def main():
    global conn_mgr_client, conn_mgr_transport, conn_mgr_sess_hdl

    try:
        discover_controller_register_fields()

        initialize_ports(target=target, port_table=t_port, port_configs=PORT_CONFIGS)

        clear_program_tables()
        clear_pre_entries(target=target, pre_mgid_table=t_pre_mgid, pre_node_table=t_pre_node)
        disable_all_pktgen_apps(pkt_gen_target=pkt_gen_target, pktgen_app_cfg_table=t_pktgen_app_cfg)

        port_states = create_sync_port_status_from_hw(t_port, t_port_status, target, HOSTS_BRIDGE_PORTS)

        for dev_port, is_up in port_states.items():
            logger.info("port_status[%s] = %s", dev_port, "up" if is_up else "down")

        program_flood_groups(target=target, pre_node_table=t_pre_node, pre_mgid_table=t_pre_mgid, flood_table=t_flood, host_ports=HOSTS_BRIDGE_PORTS, base_mgid=BASE_MGID, base_node_id=BASE_NODE_ID)
        program_pktgen_port_down(pkt_gen_target=pkt_gen_target, pktgen_app_cfg_table=t_pktgen_app_cfg, pktgen_port_cfg_table=t_pktgen_port_cfg, app_id=PKTGEN_PORT_DOWN_APP_ID, src_port=PKTGEN_SRC_PORT)

        conn_mgr_client, conn_mgr_transport, conn_mgr_sess_hdl = connect_conn_mgr()
        arm_pktgen_port_down_ports(conn_mgr_client=conn_mgr_client, sess_hdl=conn_mgr_sess_hdl, device_id=DEVICE_ID, ports=HOSTS_BRIDGE_PORTS)

        dump_table(target, t_flood, "flood_by_ingress")
        dump_table(target, t_pre_mgid, "$pre.mgid")
        dump_table(target, t_pre_node, "$pre.node")
        dump_table(target, t_port_status, "port_status")
        dump_table(target, t_port, "$PORT")
        dump_table(pkt_gen_target, t_pktgen_app_cfg, "$tf1.pktgen.app_cfg")

        open_cpu_interface()
        main_loop()

    finally:
        cleanup()


if __name__ == "__main__":
    main()