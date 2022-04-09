#!/usr/bin/env python3
import argparse
import os
import sys
from time import sleep

import grpc

# Import P4Runtime lib from parent utils dir
# Probably there's a better way of doing this.
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '../../utils/'))
import p4runtime_lib.bmv2
import p4runtime_lib.helper
from p4runtime_lib.error_utils import printGrpcError
from p4runtime_lib.switch import ShutdownAllSwitchConnections


"""
SWITCH_TO_HOST_PORT and SWITCH_TO_SWITCH

这里是按照对应的拓扑结构图配置的端口，同时也是参照对应的 topology.json 
links 里配置的端口，如果要自定义端口，记得同步修改还 json 文件 
如果要增加主机的话需要注意配置 runtime.json 以及 子网掩码划分要合理 

"""
# s1 topology
S1_TO_H11_PORT = 1
S1_TO_H1_PORT = 2

S1_TO_S2_PORT = 3
S1_TO_S3_PORT = 4

# s2 topology
S2_TO_H22_PORT = 1
S2_TO_H2_PORT = 2

S2_TO_S1_PORT = 3
S2_TO_S3_PORT = 4

#s3 topology
S3_TO_H3_PORT = 1

S3_TO_S1_PORT = 2
S3_TO_S2_PORT = 3


# 通过交换机写入规则，传入目的的 eth 地址和 ip 地址，使用子网掩码来划分不同网段并传入egress 端口
def writeIpv4Rules(p4info_helper, sw, dst_eth_addr, dst_ip_addr, port_id, subnet_mask=32):
    """
    :param p4info_helper: the P4Info helper
    :param sw: the  switch connection
    :param dst_eth_addr: the destination IP to match in the ingress rule
    :param dst_ip_addr: the destination Ethernet address to write in the
                        egress rule
    :param subnet_mask: the cider is used to divide the IP network into several smaller sub-networks
    32 represent to be 32 '1', the large network
    :param port_id : the port
    """
    # 1) Tunnel Ingress Rule
    table_entry = p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": (dst_ip_addr, subnet_mask)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": dst_eth_addr,
            "port": port_id
        })
    sw.WriteTableEntry(table_entry)
    print("Installed  rule on %s" % sw.name)


def readTableRules(p4info_helper, sw):
    """
    Reads the table entries from all tables on the switch.

    :param p4info_helper: the P4Info helper
    :param sw: the switch connection
    """
    print('\n----- Reading tables rules for %s -----' % sw.name)
    for response in sw.ReadTableEntries():
        for entity in response.entities:
            entry = entity.table_entry
            # TODO For extra credit, you can use the p4info_helper to translate
            #      the IDs in the entry to names
            # 获取入口流表名并打印
            table_name = p4info_helper.get_tables_name(entry.table_id)
            print('table name: %s' % table_name, end='\n')
            # 获取匹配字段并打印
            for m in entry.match:
                print(p4info_helper.get_match_field_name(table_name, m.field_id), end=' ')
                print('%r' % (p4info_helper.get_match_field_value(m),), end=' ')
            # 打印流表中的行为名
            action = entry.action.action
            action_name = p4info_helper.get_actions_name(action.action_id)
            print('->', action_name, end=' ')
            # 打印行为的传入参数
            for p in action.params:
                print(p4info_helper.get_action_param_name(action_name, p.param_id), end=' ')
                print('%r' % p.value, end=' ')
            print()


def printCounter(p4info_helper, sw, counter_name, index):    # 打印传输的数据

    """
    Reads the specified counter at the specified index from the switch. In our
    program, the index is the tunnel ID. If the index is 0, it will return all
    values from the counter.

    :param p4info_helper: the P4Info helper
    :param sw:  the switch connection
    :param counter_name: the name of the counter from the P4 program
    :param index: the counter index (in our case, the tunnel ID)
    """
    for response in sw.ReadCounters(p4info_helper.get_counters_id(counter_name), index):
        for entity in response.entities:
            counter = entity.counter_entry
            print("%s %s %d: %d packets (%d bytes)" % (
                sw.name, counter_name, index,
                counter.data.packet_count, counter.data.byte_count
            ))

def main(p4info_file_path, bmv2_file_path):
    # Instantiate a P4Runtime helper from the p4info file
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_file_path)

    try:
        # Create a switch connection object for s1 and s2;
        # this is backed by a P4Runtime gRPC connection.
        # Also, dump all P4Runtime messages sent to switch to given txt files.
        s1 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s1',
            address='127.0.0.1:50051',
            device_id=0,
            proto_dump_file='logs/s1-p4runtime-requests.txt')
        s2 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s2',
            address='127.0.0.1:50052',
            device_id=1,
            proto_dump_file='logs/s2-p4runtime-requests.txt')
        s3 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s3',
            address='127.0.0.1:50053',
            device_id=2,
            proto_dump_file='logs/s3-p4runtime-requests.txt')

        # Send master arbitration update message to establish this controller as
        # master (required by P4Runtime before performing any other write operation)
        s1.MasterArbitrationUpdate()
        s2.MasterArbitrationUpdate()
        s3.MasterArbitrationUpdate()


        # Install the P4 program on the switches
        s1.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                       bmv2_json_file_path=bmv2_file_path)
        print("Installed P4 Program using SetForwardingPipelineConfig on s1")
        s2.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                       bmv2_json_file_path=bmv2_file_path)
        print("Installed P4 Program using SetForwardingPipelineConfig on s2")
        s3.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                       bmv2_json_file_path=bmv2_file_path)
        print("Installed P4 Program using SetForwardingPipelineConfig on s3")

        # Write the rules on s1
        print("write the rules on s1")
        writeIpv4Rules(p4info_helper, sw=s1, dst_eth_addr="08:00:00:00:01:11", dst_ip_addr="10.0.1.11",
                       port_id=S1_TO_H11_PORT, subnet_mask=32)
        writeIpv4Rules(p4info_helper, sw=s1, dst_eth_addr="08:00:00:00:01:01", dst_ip_addr="10.0.1.1",
                       port_id=S1_TO_H1_PORT, subnet_mask=32)
        writeIpv4Rules(p4info_helper, sw=s1, dst_eth_addr="08:00:00:00:02:00", dst_ip_addr="10.0.2.0",
                       port_id=S1_TO_S2_PORT, subnet_mask=24)
        writeIpv4Rules(p4info_helper, sw=s1, dst_eth_addr="08:00:00:00:03:00", dst_ip_addr="10.0.3.0",
                       port_id=S1_TO_S3_PORT, subnet_mask=24)
        # Write the rules on s2
        print("write the rules on s2")
        writeIpv4Rules(p4info_helper, sw=s2, dst_eth_addr="08:00:00:00:02:22", dst_ip_addr="10.0.2.22",
                       port_id=S2_TO_H22_PORT, subnet_mask=32)
        writeIpv4Rules(p4info_helper, sw=s2, dst_eth_addr="08:00:00:00:02:02", dst_ip_addr="10.0.2.2",
                       port_id=S2_TO_H2_PORT, subnet_mask=32)
        writeIpv4Rules(p4info_helper, sw=s2, dst_eth_addr="08:00:00:00:01:00", dst_ip_addr="10.0.1.0",
                       port_id=S2_TO_S1_PORT, subnet_mask=24)
        writeIpv4Rules(p4info_helper, sw=s2, dst_eth_addr="08:00:00:00:03:00", dst_ip_addr="10.0.3.0",
                       port_id=S2_TO_S3_PORT, subnet_mask=24)
        # Write the rules on s3
        print("write the rules on s3")
        writeIpv4Rules(p4info_helper, sw=s3, dst_eth_addr="08:00:00:00:03:03", dst_ip_addr="10.0.3.3",
                       port_id=S3_TO_H3_PORT, subnet_mask=32)
        writeIpv4Rules(p4info_helper, sw=s3, dst_eth_addr="08:00:00:00:01:00", dst_ip_addr="10.0.1.0",
                       port_id=S3_TO_S1_PORT, subnet_mask=24)
        writeIpv4Rules(p4info_helper, sw=s3, dst_eth_addr="08:00:00:00:02:00", dst_ip_addr="10.0.2.0",
                       port_id=S3_TO_S2_PORT, subnet_mask=24)

        readTableRules(p4info_helper, s1)
        readTableRules(p4info_helper, s2)
        readTableRules(p4info_helper, s3)
        print("Complete readTableRules")

    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

if __name__ == '__main__':
    # 创建一个解析对象 parser,并给其命名为 'P4Runtime Controller'
    parser = argparse.ArgumentParser(description='P4Runtime Controller')
    # 创建的解析对象添加相应的帮助命令行选项 查看 p4info 和 bmv2.json 文件
    parser.add_argument('--p4info', help='p4info proto in text format from p4c',
                        type=str, action="store", required=False,
                        default='./build/ecn.p4.p4info.txt')
    parser.add_argument('--bmv2-json', help='BMv2 JSON file from p4c',
                        type=str, action="store", required=False,
                        default='./build/ecn.json')
    args = parser.parse_args()

    # 如果对应的文件路径不存在， 输出对应的反馈
    if not os.path.exists(args.p4info):
        parser.print_help()
        print("\np4info file not found: %s\nHave you run 'make'?" % args.p4info)
        parser.exit(1)
    if not os.path.exists(args.bmv2_json):
        parser.print_help()
        print("\nBMv2 JSON file not found: %s\nHave you run 'make'?" % args.bmv2_json)
        parser.exit(1)
    main(args.p4info, args.bmv2_json)
