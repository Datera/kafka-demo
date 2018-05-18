#!/usr/bin/env python

from __future__ import (print_function, unicode_literals, division,
                        absolute_import)

import argparse
import json
import os
import sys
import time

import paramiko

SUCCESS = 0
FAILURE = 1
VERBOSE = False


def read_stderr(chan, nbytes=500):
    data = []
    while True:
        new_data = chan.recv_stderr(nbytes)
        if new_data == '':
            return "".join(data)
        data.append(new_data)


class Host(object):
    def __init__(self, host, user, password=None, hkeys=False):
        self.host = host
        self.user = user
        self.password = password
        self.hkeys = hkeys
        self.ssh = get_ssh(
            self.host, self.user, password=self.password, hkeys=self.hkeys)
        # Test connection
        assert self.exe("ls -halt").strip() != ''

    def exe(self, cmd, failok=False):
        vprint("Running on host {}, cmd: {}".format(self.host, cmd))
        _, stdout, stderr = self.ssh.exec_command(cmd)
        if stdout.channel.recv_exit_status() != 0:
            raise ValueError(stderr.read().strip())
        result = stdout.read().strip()
        vprint(result)
        return result

    def exe_bg(self, cmd, failok=False, directory=None,
               logfile="my-process.log"):
        cmd = "cd {directory} && nohup {cmd} > {logfile} 2>&1 &".format(
            directory=directory, cmd=cmd, logfile=logfile)
        vprint("Running in background on host {}, cmd: {}".format(
            self.host, cmd))
        tp = self.ssh.get_transport()
        ch = tp.open_session()
        ch.exec_command(cmd)
        if ch.recv_exit_status() != 0:
            raise ValueError(read_stderr(ch))


def vprint(*args, **kwargs):
    if VERBOSE:
        print(*args, **kwargs)


def get_ssh(host, user, password=None, hkeys=False):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if hkeys:
        ssh.load_system_host_keys()
        ssh.connect(host, username=user, timeout=5)
    else:
        ssh.connect(host, username=user, password=password, timeout=5)
    return ssh


def main(args):
    if not args.password:
        khost = Host(args.kafka_host, args.username, hkeys=True)
    else:
        khost = Host(args.kafka_host, args.username, args.password)
    home = khost.exe("echo $HOME")
    mount = os.path.join(home, args.kafka_mount)
    if args.operation == "status":
        pids = khost.exe(
            "ps -ef | grep kafka | grep -v grep | awk '{print $2}'").split()
        if len(pids) > 0:
            print("Kafka is running")
        else:
            print("Kafka is not running")
        bkrs = khost.exe("echo dump | nc {} 2181 | grep 'brokers/ids'".format(
            args.zookeeper)).split()
        print("Brokers found: {}".format(len(bkrs)))
        print("Brokers: \n{}".format("\n".join(bkrs)))
    elif args.operation == "kill":
        # Kill kafka
        pids = khost.exe(
            "ps -ef | grep kafka | grep -v grep | awk '{print $2}'").split()
        spids = " ".join(pids)
        vprint("Killing kafka processes {}".format(spids))
        khost.exe("sudo kill -9 {}".format(spids))
        # Unmount directory
        vprint("Unmounting directory {}".format(mount))
        khost.exe("sudo umount {}".format(mount))
    elif args.operation == "start":
        devs = json.loads(khost.exe("lsblk --json --fs"))["blockdevices"]
        found = None
        for dev in devs:
            if dev["fstype"] == "xfs":
                found = "/dev/{}".format(dev["name"])
                break
        else:
            raise EnvironmentError("XFS device not found")
        # Mount device
        khost.exe("sudo mount -o {opts} {dev} {mount}".format(
            opts=args.mount_opts, dev=found, mount=mount))
        vprint("Starting kafka server on host {}".format(args.kafka_host))
        khost.exe_bg(
            "sudo ./kafka-server-start.sh ../config/server.properties",
            directory=args.bin_folder, logfile="~kafka.log")
        time.sleep(5)
        new_pids = khost.exe(
            "ps -ef | grep kafka | grep -v grep | awk '{print $2}'").split()
        if len(new_pids) < 1:
            khost.exe("cat ~/kafka.log")
            raise ValueError("Kafka did not start")
    return SUCCESS


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["kill", "start", "status"])
    parser.add_argument("kafka_host")
    parser.add_argument("-u", "--username")
    parser.add_argument("-p", "--password")
    parser.add_argument("-b", "--bin-folder", default="kafka_2.11-1.1.0/bin")
    parser.add_argument("-m", "--kafka-mount", default="kafka-logs",
                        help="Must be under home directory")
    parser.add_argument("-o", "--mount-opts",
                        default="rw,sync,relatime,wsync,attr2,inode64,noquota")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-z", "--zookeeper", default="203.0.113.107")
    args = parser.parse_args()
    if args.verbose:
        VERBOSE = True
    sys.exit(main(args))
