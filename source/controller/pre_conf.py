#!/usr/bin/env python3

from grpc_tables import clear_table, add_table_entry
from grpc_pre import add_replication_node, add_multicast_group


def mgid_for_ingress_port(base_mgid, port):
    return int(base_mgid) + int(port)


def node_id_for_ingress_port(base_node_id, port):
    return int(base_node_id) + int(port)


def clear_pre_entries(target, pre_mgid_table, pre_node_table):
    clear_table(target, pre_mgid_table)
    clear_table(target, pre_node_table)


def add_flood_selector_entry(target, flood_table, ingress_port, mgid):
    add_table_entry(
        table_obj=flood_table,
        target=target,
        key_fields=[
            ("md.flood_src_port", int(ingress_port)),
        ],
        data_fields=[
            ("gid", int(mgid)),
        ],
        action_name="SwitchIngress.set_flood_grp"
    )


def program_flood_groups(target, pre_node_table, pre_mgid_table, flood_table, host_ports, base_mgid, base_node_id):
    for ingress_port in host_ports:
        mgid = mgid_for_ingress_port(base_mgid, ingress_port)
        node_id = node_id_for_ingress_port(base_node_id, ingress_port)

        replica_ports = [
            port for port in host_ports
            if int(port) != int(ingress_port)
        ]

        add_replication_node(
            target=target,
            pre_node_table=pre_node_table,
            node_id=node_id,
            replica_ports=replica_ports
        )

        add_multicast_group(
            target=target,
            pre_mgid_table=pre_mgid_table,
            mgid=mgid,
            node_id=node_id
        )

        add_flood_selector_entry(
            target=target,
            flood_table=flood_table,
            ingress_port=ingress_port,
            mgid=mgid
        )