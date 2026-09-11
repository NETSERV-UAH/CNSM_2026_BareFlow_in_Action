#!/usr/bin/env python3

import time

from grpc_tables import clear_table, add_table_entry, modify_table_entry, delete_table_entry, read_table, read_table_entry
from grpc_regs import discover_register_field_names, write_register, read_register
from grpc_auxiliars import mac_to_int, int_to_mac, get_field


def alloc_reg_index(free_reg_indices):
    if not free_reg_indices:
        raise RuntimeError("No free register indices remain")

    return int(free_reg_indices.popleft())


def free_reg_index(free_reg_indices, index, reg_array_size):
    index = int(index)

    if 0 <= index < int(reg_array_size):
        free_reg_indices.append(index)


def discover_mac_register_fields(t_reg_tstamp, t_reg_valid, target):
    reg_tstamp_field = discover_register_field_names(t_reg_tstamp, target)
    reg_valid_field = discover_register_field_names(t_reg_valid, target)

    return reg_tstamp_field, reg_valid_field


def set_tstamp_slot(t_reg_tstamp, target, reg_tstamp_field, reg_index, ts32):
    if reg_tstamp_field is None:
        raise RuntimeError("The mac_state_tstamp field has not been discovered")

    write_register(
        table_obj=t_reg_tstamp,
        target=target,
        reg_index=reg_index,
        field_names=reg_tstamp_field,
        values=ts32,
        bit_widths=32
    )


def set_valid_slot(t_reg_valid, target, reg_valid_field, reg_index, valid):
    if reg_valid_field is None:
        raise RuntimeError("The mac_state_valid field has not been discovered")

    write_register(
        table_obj=t_reg_valid,
        target=target,
        reg_index=reg_index,
        field_names=reg_valid_field,
        values=valid,
        bit_widths=1
    )


def read_tstamp_slot(t_reg_tstamp, target, reg_tstamp_field, reg_index):
    if reg_tstamp_field is None:
        return None

    return read_register(
        table_obj=t_reg_tstamp,
        target=target,
        reg_index=reg_index,
        field_names=reg_tstamp_field
    )


def read_valid_slot(t_reg_valid, target, reg_valid_field, reg_index):
    if reg_valid_field is None:
        return None

    return read_register(
        table_obj=t_reg_valid,
        target=target,
        reg_index=reg_index,
        field_names=reg_valid_field
    )


def clear_register_slot(t_reg_tstamp, t_reg_valid, target, reg_tstamp_field, reg_valid_field, reg_index):
    set_tstamp_slot(
        t_reg_tstamp=t_reg_tstamp,
        target=target,
        reg_tstamp_field=reg_tstamp_field,
        reg_index=reg_index,
        ts32=0
    )

    set_valid_slot(
        t_reg_valid=t_reg_valid,
        target=target,
        reg_valid_field=reg_valid_field,
        reg_index=reg_index,
        valid=0
    )


def clear_mac_tables(target, t_mac_state, t_flood):
    clear_table(target, t_mac_state)
    clear_table(target, t_flood)


def add_mac_state_entry(target, t_mac_state, mac, port, reg_dir):
    add_table_entry(
        table_obj=t_mac_state,
        target=target,
        key_fields=[
            ("md.lookup_mac", mac_to_int(mac)),
        ],
        data_fields=[
            ("port", int(port)),
            ("reg_dir", int(reg_dir)),
        ],
        action_name="SwitchIngress.mac_hit"
    )


def modify_mac_state_entry(target, t_mac_state, mac, port, reg_dir):
    modify_table_entry(
        table_obj=t_mac_state,
        target=target,
        key_fields=[
            ("md.lookup_mac", mac_to_int(mac)),
        ],
        data_fields=[
            ("port", int(port)),
            ("reg_dir", int(reg_dir)),
        ],
        action_name="SwitchIngress.mac_hit"
    )


def delete_mac_state_entry(target, t_mac_state, mac):
    delete_table_entry(
        table_obj=t_mac_state,
        target=target,
        key_fields=[
            ("md.lookup_mac", mac_to_int(mac)),
        ]
    )


def wait_until_mac_state_present(target, t_mac_state, mac, expected_port, expected_reg_dir, timeout_secs, poll_secs):
    mac = mac_to_int(mac)
    expected_port = int(expected_port)
    expected_reg_dir = int(expected_reg_dir)

    deadline = time.time() + float(timeout_secs)

    while time.time() < deadline:
        try:
            rows = read_table_entry(
                table_obj=t_mac_state,
                target=target,
                key_fields=[
                    ("md.lookup_mac", mac),
                ],
                from_hw=True
            )

            for row in rows:
                data_dict = row["data"]

                port = get_field(data_dict, ["port"])
                reg_dir = get_field(data_dict, ["reg_dir"])

                if port is None or reg_dir is None:
                    continue

                if int(port) == expected_port and int(reg_dir) == expected_reg_dir:
                    return True

        except Exception:
            pass

        time.sleep(poll_secs)

    return False


def read_mac_state_rows(target, t_mac_state, mac_db):
    rows = []

    table_rows = read_table(
        table_obj=t_mac_state,
        target=target,
        from_hw=True
    )

    for table_row in table_rows:
        key_dict = table_row["key"]
        data_dict = table_row["data"]

        mac = get_field(key_dict, ["md.lookup_mac"])
        port = get_field(data_dict, ["port"])
        reg_dir = get_field(data_dict, ["reg_dir"])

        if mac is None:
            continue

        mac_int = mac_to_int(mac)

        rows.append({
            "mac": mac_int,
            "port": int(port) if port is not None else None,
            "reg_dir": int(reg_dir) if reg_dir is not None else None,
            "valid_sw": mac_db.get(mac_int, {}).get("valid"),
        })

    rows.sort(key=lambda row: row["mac"])
    return rows


def get_mac_table_rows_with_registers(target, t_mac_state, t_reg_tstamp, t_reg_valid, reg_tstamp_field, reg_valid_field, mac_db):
    rows = read_mac_state_rows(
        target=target,
        t_mac_state=t_mac_state,
        mac_db=mac_db
    )

    for row in rows:
        row["ts32"] = read_tstamp_slot(
            t_reg_tstamp=t_reg_tstamp,
            target=target,
            reg_tstamp_field=reg_tstamp_field,
            reg_index=row["reg_dir"]
        )

        row["valid_hw"] = read_valid_slot(
            t_reg_valid=t_reg_valid,
            target=target,
            reg_valid_field=reg_valid_field,
            reg_index=row["reg_dir"]
        )

    return rows


def install_or_update_source_mac(target, t_mac_state, t_reg_tstamp, t_reg_valid, reg_tstamp_field, reg_valid_field, free_reg_indices, mac_db, mac, ingress_port, ts32, mac_state_install_timeout_secs, mac_state_install_poll_secs):
    mac = mac_to_int(mac)
    ingress_port = int(ingress_port)
    ts32 = int(ts32) & 0xFFFFFFFF

    if mac not in mac_db:
        reg_dir = alloc_reg_index(free_reg_indices)

        set_tstamp_slot(
            t_reg_tstamp=t_reg_tstamp,
            target=target,
            reg_tstamp_field=reg_tstamp_field,
            reg_index=reg_dir,
            ts32=ts32
        )

        set_valid_slot(
            t_reg_valid=t_reg_valid,
            target=target,
            reg_valid_field=reg_valid_field,
            reg_index=reg_dir,
            valid=1
        )

        add_mac_state_entry(
            target=target,
            t_mac_state=t_mac_state,
            mac=mac,
            port=ingress_port,
            reg_dir=reg_dir
        )

        installed = wait_until_mac_state_present(
            target=target,
            t_mac_state=t_mac_state,
            mac=mac,
            expected_port=ingress_port,
            expected_reg_dir=reg_dir,
            timeout_secs=mac_state_install_timeout_secs,
            poll_secs=mac_state_install_poll_secs
        )

        mac_db[mac] = {
            "port": ingress_port,
            "reg_dir": reg_dir,
            "valid": 1,
        }

        return installed, "learn", reg_dir, None

    old_port = mac_db[mac]["port"]
    reg_dir = mac_db[mac]["reg_dir"]

    set_tstamp_slot(
        t_reg_tstamp=t_reg_tstamp,
        target=target,
        reg_tstamp_field=reg_tstamp_field,
        reg_index=reg_dir,
        ts32=ts32
    )

    set_valid_slot(
        t_reg_valid=t_reg_valid,
        target=target,
        reg_valid_field=reg_valid_field,
        reg_index=reg_dir,
        valid=1
    )

    modify_mac_state_entry(
        target=target,
        t_mac_state=t_mac_state,
        mac=mac,
        port=ingress_port,
        reg_dir=reg_dir
    )

    installed = wait_until_mac_state_present(
        target=target,
        t_mac_state=t_mac_state,
        mac=mac,
        expected_port=ingress_port,
        expected_reg_dir=reg_dir,
        timeout_secs=mac_state_install_timeout_secs,
        poll_secs=mac_state_install_poll_secs
    )

    mac_db[mac]["port"] = ingress_port
    mac_db[mac]["valid"] = 1

    if int(old_port) != int(ingress_port):
        return installed, "move", reg_dir, old_port

    return installed, "refresh", reg_dir, old_port


def remove_mac(target, t_mac_state, t_reg_tstamp, t_reg_valid, reg_tstamp_field, reg_valid_field, free_reg_indices, reg_array_size, mac_db, mac):
    mac = mac_to_int(mac)

    if mac not in mac_db:
        return False, None

    reg_dir = mac_db[mac]["reg_dir"]

    delete_mac_state_entry(
        target=target,
        t_mac_state=t_mac_state,
        mac=mac
    )

    clear_register_slot(
        t_reg_tstamp=t_reg_tstamp,
        t_reg_valid=t_reg_valid,
        target=target,
        reg_tstamp_field=reg_tstamp_field,
        reg_valid_field=reg_valid_field,
        reg_index=reg_dir
    )

    free_reg_index(
        free_reg_indices=free_reg_indices,
        index=reg_dir,
        reg_array_size=reg_array_size
    )

    del mac_db[mac]

    return True, reg_dir


def is_broadcast_mac(mac):
    return int(mac) == 0xFFFFFFFFFFFF


def resolve_destination(mac_db, dst_mac):
    dst_mac = mac_to_int(dst_mac)

    if is_broadcast_mac(dst_mac):
        return ("broadcast", None)

    if dst_mac in mac_db:
        entry = mac_db[dst_mac]

        if int(entry.get("valid", 0)) != 0:
            return ("unicast", int(entry["port"]))

    return ("unknown", None)


def source_mac_move_allowed(t_reg_tstamp, t_reg_valid, target, reg_tstamp_field, reg_valid_field, reg_dir, ts32, block_time_cte):
    valid_hw = read_valid_slot(
        t_reg_valid=t_reg_valid,
        target=target,
        reg_valid_field=reg_valid_field,
        reg_index=reg_dir
    )

    tstamp_hw = read_tstamp_slot(
        t_reg_tstamp=t_reg_tstamp,
        target=target,
        reg_tstamp_field=reg_tstamp_field,
        reg_index=reg_dir
    )

    if valid_hw is None or tstamp_hw is None:
        return False, valid_hw, tstamp_hw

    if int(valid_hw) == 0:
        return True, valid_hw, tstamp_hw

    diff = (int(ts32) - int(tstamp_hw)) & 0xFFFFFFFF

    if diff > int(block_time_cte):
        return True, valid_hw, tstamp_hw

    return False, valid_hw, tstamp_hw