#!/usr/bin/env python3
from grpc_tables import clear_table, dump_table, add_table_entry, modify_table_entry, read_table_entry


def clear_port_status_table(target, port_status_table):
    clear_table(target, port_status_table)


def _extract_plain_value(value):
    if isinstance(value, dict) and "value" in value:
        return value["value"]

    return value


def read_port_is_up(port_table, target, dev_port):
    dev_port = int(dev_port)

    rows = read_table_entry(
        table_obj=port_table,
        target=target,
        key_fields=[("$DEV_PORT", dev_port)],
        from_hw=True
    )

    if not rows:
        return False

    data_dict = rows[0]["data"]

    for field_name in ("$PORT_UP", "$IS_UP", "$PORT_ENABLE"):
        if field_name in data_dict:
            return bool(_extract_plain_value(data_dict[field_name]))

    return False


def add_port_status_entry(port_status_table, target, dev_port, is_up):
    dev_port = int(dev_port)
    is_up_int = 1 if is_up else 0

    key_fields = [("md.lookup_port", dev_port)]
    data_fields = [("is_up", is_up_int)]

    add_table_entry(port_status_table, target, key_fields, data_fields, "SwitchIngress.port_status_hit")

    return bool(is_up_int)


def modify_port_status_entry(port_status_table, target, dev_port, is_up):
    dev_port = int(dev_port)
    is_up_int = 1 if is_up else 0

    key_fields = [("md.lookup_port", dev_port)]
    data_fields = [("is_up", is_up_int)]

    modify_table_entry(port_status_table, target, key_fields, data_fields, "SwitchIngress.port_status_hit")

    return bool(is_up_int)


def create_sync_port_status_from_hw(port_table, port_status_table, target, host_ports, dump_after_sync=False):
    clear_port_status_table(target, port_status_table)

    port_states = {}

    for dev_port in host_ports:
        is_up = read_port_is_up(port_table, target, dev_port)
        written_state = add_port_status_entry(port_status_table, target, dev_port, is_up)
        port_states[int(dev_port)] = written_state

    if dump_after_sync:
        dump_table(target, port_status_table, "port_status")

    return port_states


def sync_port_status_from_hw(port_table, port_status_table, target, host_ports, dump_after_sync=False):
    port_states = {}

    for dev_port in host_ports:
        is_up = read_port_is_up(port_table, target, dev_port)
        written_state = modify_port_status_entry(port_status_table, target, dev_port, is_up)
        port_states[int(dev_port)] = written_state

    if dump_after_sync:
        dump_table(target, port_status_table, "port_status")

    return port_states