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
        vprint("Status:", result.status)
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
    poll_vol("volume", vol_id)


def delete_volume(conn, vol_id):
    vprint("Deleting Volume:", vol_id)
    conn.block_storage.delete_volume(vol_id)


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


def main(args):
    conn = openstack.connect()
    vol_id = vol_by_name(conn, args.volume_name).id
    type_id = type_by_name(conn, args.dest_type_name)
    migrate_to_type(conn, vol_id, type_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('kafka_node')
    parser.add_argument('volume_name')
    parser.add_argument('dest_type_name')
    args = parser.parse_args()
    sys.exit(main(args))
