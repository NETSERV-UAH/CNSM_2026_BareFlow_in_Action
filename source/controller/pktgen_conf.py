#!/usr/bin/env python3
from thrift.transport import TSocket
from thrift.transport import TTransport
from thrift.protocol import TBinaryProtocol
from thrift.protocol import TMultiplexedProtocol

from conn_mgr_pd_rpc import conn_mgr
from grpc_tables import add_table_entry, modify_table_entry, read_table

def configure_pktgen_port_down_app(pkt_gen_target, pktgen_app_cfg_table, app_id, src_port):
    modify_table_entry(
        table_obj=pktgen_app_cfg_table,
        target=pkt_gen_target,
        key_fields=[
            ("app_id", int(app_id)),
        ],
        data_fields=[
            ("app_enable", False),
            ("pkt_len", 1018),
            ("pkt_buffer_offset", 144),
            ("pipe_local_source_port", int(src_port)),
            ("increment_source_port", False),
            ("batch_count_cfg", 0),
            ("packets_per_batch_cfg", 0),
            ("ibg", 1),
            ("ibg_jitter", 0),
            ("ipg", 1000),
            ("ipg_jitter", 500),
            ("batch_counter", 0),
            ("pkt_counter", 0),
            ("trigger_counter", 0),
        ],
        action_name="trigger_port_down"
    )


def enable_pktgen_injection_port( pkt_gen_target, pktgen_port_cfg_table, src_port):
    key_fields = [
        ("dev_port", int(src_port)),
    ]

    data_fields = [
        ("pktgen_enable", True),
    ]

    modify_table_entry(
        table_obj=pktgen_port_cfg_table,
        target=pkt_gen_target,
        key_fields=key_fields,
        data_fields=data_fields,
        action_name=None
    )


def enable_pktgen_port_down_app( pkt_gen_target, pktgen_app_cfg_table, app_id):
    modify_table_entry(
        table_obj=pktgen_app_cfg_table,
        target=pkt_gen_target,
        key_fields=[
            ("app_id", int(app_id)),
        ],
        data_fields=[
            ("app_enable", True),
        ],
        action_name="trigger_port_down"
    )


def program_pktgen_port_down(pkt_gen_target, pktgen_app_cfg_table, pktgen_port_cfg_table, app_id, src_port):
    
    enable_pktgen_injection_port(
        pkt_gen_target=pkt_gen_target,
        pktgen_port_cfg_table=pktgen_port_cfg_table,
        src_port=src_port
    )

    configure_pktgen_port_down_app(
        pkt_gen_target=pkt_gen_target,
        pktgen_app_cfg_table=pktgen_app_cfg_table,
        app_id=app_id,
        src_port=src_port
    )

    enable_pktgen_port_down_app(
        pkt_gen_target=pkt_gen_target,
        pktgen_app_cfg_table=pktgen_app_cfg_table,
        app_id=app_id
    )

def disable_pktgen_port_down_app(
    pkt_gen_target,
    pktgen_app_cfg_table,
    app_id
):
    modify_table_entry(
        table_obj=pktgen_app_cfg_table,
        target=pkt_gen_target,
        key_fields=[
            ("app_id", int(app_id)),
        ],
        data_fields=[
            ("app_enable", False),
        ],
        action_name="trigger_port_down"
    )

def disable_all_pktgen_apps(pkt_gen_target, pktgen_app_cfg_table):
    
    rows = read_table(
        table_obj=pktgen_app_cfg_table,
        target=pkt_gen_target,
        from_hw=False
    )

    for row in rows:
        key_dict = row["key"]
        data_dict = row["data"]

        app_id = key_dict.get("app_id", {}).get("value")
        action_name = data_dict.get("action_name")

        if app_id is None or action_name is None:
            continue


        modify_table_entry(
            table_obj=pktgen_app_cfg_table,
            target=pkt_gen_target,
            key_fields=[
                ("app_id", int(app_id)),
            ],
            data_fields=[
                ("app_enable", False),
            ],
            action_name=action_name
        )

def connect_conn_mgr(thrift_host="localhost", thrift_port=9090):
    transport = TSocket.TSocket(thrift_host, thrift_port)
    transport = TTransport.TBufferedTransport(transport)

    protocol = TBinaryProtocol.TBinaryProtocol(transport)
    conn_mgr_protocol = TMultiplexedProtocol.TMultiplexedProtocol(
        protocol,
        "conn_mgr"
    )

    conn_mgr_client = conn_mgr.Client(conn_mgr_protocol)

    transport.open()
    sess_hdl = conn_mgr_client.client_init()

    return conn_mgr_client, transport, sess_hdl

def close_conn_mgr(conn_mgr_client, transport, sess_hdl):
    try:
        if conn_mgr_client is not None and sess_hdl is not None:
            conn_mgr_client.client_cleanup(sess_hdl)
    finally:
        if transport is not None:
            transport.close()

def arm_pktgen_port_down_ports(conn_mgr_client, sess_hdl, device_id, ports):
    for port in ports:
        conn_mgr_client.pktgen_clear_port_down(
            sess_hdl,
            int(device_id),
            int(port)
        )

    conn_mgr_client.complete_operations(sess_hdl)