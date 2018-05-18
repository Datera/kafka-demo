#!/usr/bin/env python

from __future__ import (print_function, unicode_literals, division,
                        absolute_import)

import argparse
import subprocess
import sys
import threading
import time

try:
    import queue
except ImportError:
    import Queue
    queue = Queue

import openstack

VOL_INTERVAL = 20
WORKERS = 5
VERBOSE = True
PLOCK = threading.Lock()

pqueue = queue.Queue()


def vprint(*args, **kwargs):
    if VERBOSE:
        PLOCK.acquire()
        print(*args, **kwargs)
        PLOCK.release()


def poll_vol(conn, vid, timeout=5, status="available"):
    while timeout:
        time.sleep(1)
        result = conn.block_storage.get_volume(vid)
        vprint("Status:", result.status, end='\r')
        if result.status.strip() == status:
            break
        timeout -= 1
    if not timeout:
        raise ValueError("volume {} was not available before timeout was "
                         "reached".format(vid))


def migrate_to_type(conn, vol_id, vtype):
    vprint("Migrating Ceph Volume:", vol_id, "To Datera")
    exe("cinder retype --migration-policy on-demand "
        "{volume} {volume_type}".format(volume=vol_id, volume_type=vtype))
    poll_vol(conn, vol_id, timeout=600)
    print("Retype complete")


def wait_for_retype(conn, vol_name, vol_id):
    # This whole thing is a hack for weird behavior during retype where
    # sometimes the old volume isn't deleted in Newton
    timeout = 600
    while timeout:
        found = list(filter(bool, exe(
            "openstack volume list | grep {}".format(vol_name)).split("\n")))
        if len(found) == 1:
            break
        timeout -= 1
    if timeout == 0:
        raise ValueError(
            "Reached timeout and volume {} still has two entries".format(
                vol_name))


def detach_volume(conn, server_id, volume_id):
    # att = filter(lambda x: x.volume_id == volume_id,
    #              conn.compute.volume_attachments(server_id))[0]
    # return conn.compute.delete_volume_attachment(att, server_id)
    exe("openstack server remove volume {} {}".format(server_id, volume_id))
    time.sleep(5)


def attach_volume(conn, server_id, volume_name):
    # conn.compute.create_volume_attachment(server_id, volume_id=volume_id)
    exe("openstack server add volume {} {}".format(server_id, volume_name))

    time.sleep(5)


def exe(cmd):
    vprint("Running cmd:", cmd)
    return subprocess.check_output(cmd, shell=True).decode("utf-8")


def vol_by_name(conn, name):
    vols = filter(lambda x: x.name == name, conn.block_storage.volumes())
    if len(vols) == 0:
        raise ValueError("No volume found with name {}".format(name))
    return vols[0]


def type_by_name(conn, name):
    types = filter(lambda x: x.name == name, conn.block_storage.types())
    if len(types) == 0:
        raise ValueError("No volume type found with name {}".format(name))
    return types[0]


def server_by_name(conn, name):
    servers = filter(lambda x: x.name == name, conn.compute.servers())
    if len(servers) == 0:
        raise ValueError("No server found with name {}".format(name))
    return servers[0]


def get_server_fip(server):
    addrs = server.addresses['selfservice']
    fips = filter(
        lambda x: x['OS-EXT-IPS:type'] == 'floating', addrs)
    if len(fips) == 0:
        raise ValueError("Could not find floating IP for server {}.  "
                         "Addresses: {}".format(server.name, server.addresses))
    return fips[0]['addr']


def kill_kafka(node):
    try:
        exe("./kafka_ops.py kill {} --username ubuntu -v".format(node))
    except subprocess.CalledProcessError:
        # sometimes it fails the first time due to a race condition
        # where the device isn't ready to be unmounted
        time.sleep(1)
        exe("./kafka_ops.py kill {} --username ubuntu -v".format(node))


def start_kafka(node):
    try:
        exe("./kafka_ops.py start {} --username ubuntu -v".format(node))
    except subprocess.CalledProcessError:
        print("Failed to start kafka node {}".format(node))
        raise


def check_ip(ip):
    try:
        exe("ping -c1 {}".format(ip))
        return True
    except subprocess.CalledProcessError as e:
        print(e)
        return False


# def tryexe(cmd):
#     try:
#         exe(cmd)
#     except subprocess.CalledProcessError as e:
#         print(e)


# def reset_node(knode, vol_name):
#     try:
#         kill_kafka(knode)
#     except Exception as e:
#         print(e)

#     tryexe("openstack server remove volume {} {}".format(knode, vol_name))
#     tryexe("openstack volume delete {}".format(vol_name))
#     tryexe("openstack volume create {} --size 10 --type Ceph-Copper"
#            "".format(vol_name))
#     tryexe("openstack server add volume {} {}".format(knode, vol_name))


def main(args):
    conn = openstack.connect()
    vtype_name = args.dest_type_name
    knames = args.kafka_names.split(",")
    vol_names = args.volume_names.split(",")
    # if args.reset:
    #     for knode, vol_name in zip(knames, vol_names):
    #         reset_node(knode, vol_name)
    #     return 0
    for knode, vol_name in zip(knames, vol_names):
        vol_id = vol_by_name(conn, vol_name).id
        type_id = type_by_name(conn, vtype_name).id
        server = server_by_name(conn, knode)
        server_id = server.id
        sip = get_server_fip(server)

        if not check_ip(sip):
            raise ValueError("Could not reach Kafka IP {}".format(sip))
        # Workflow
        print("Migrating {} with volume {} to type {}".format(
            knode, vol_name, vtype_name))
        print("Killing Kafka on node {}".format(knode))
        kill_kafka(sip)
        print("Detaching volume {} from node {}".format(vol_name, knode))
        detach_volume(conn, server_id, vol_id)
        print("Migrating volume {} to type {}".format(vol_name, vtype_name))
        migrate_to_type(conn, vol_id, type_id)
        print("Deleting old volume {}".format(vol_id))
        wait_for_retype(conn, vol_name, vol_id)
        print("Attaching volume {} to node {}".format(vol_name, knode))
        attach_volume(conn, server_id, vol_name)
        print("Starting Kafka on node {}".format(knode))
        start_kafka(sip)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('kafka_names', help="Comma separated list")
    parser.add_argument('volume_names', help="Comma separated list")
    parser.add_argument('dest_type_name')
    parser.add_argument('-r', '--reset', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    VERBOSE = args.verbose
    sys.exit(main(args))
