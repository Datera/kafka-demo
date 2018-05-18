#!/usr/bin/env python

from __future__ import (print_function, unicode_literals, division,
                        absolute_import)

import argparse
import random
import string
import sys
import threading
import time
import itertools

import kafka
import simplejson as json


def gen_messages():
    alc = list(string.ascii_lowercase)
    while True:
        yield "".join(alc[int(random.random() * 26)] for _ in range(100))


def sender(producer, flow):
    messages = gen_messages()
    topic = args.topic
    while True:
        prod = random.choice(("producera", "producerb"))
        dest = random.choice(("consumera", "consumerb"))
        for msg in itertools.islice(messages, random.randint(100, 2000)):
            producer.send(topic, {"log": msg, "dest": dest, "prod": prod})
            if flow == "dev":
                time.sleep(0.05)
    print("All Done")


def main(args):
    producer = kafka.KafkaProducer(
        bootstrap_servers=[args.broker],
        value_serializer=lambda x: json.dumps(x).encode('utf-8'))
    send = threading.Thread(target=sender, args=(producer, args.flow))
    send.daemon = True
    send.start()
    while True:
        print(int(producer.metrics()['producer-metrics'][
            'outgoing-byte-rate']) / 1000000, "MB/s", end='\r')
        time.sleep(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("topic")
    parser.add_argument("broker")
    parser.add_argument("flow", choices=["dev", "prod"])
    args = parser.parse_args()
    sys.exit(main(args))
