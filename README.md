Kafka Demo Instructions
=======================

Getting Started
----------------
* Verify that kafka-1, kafka-2 and kafka-3 servers are up and running
* Verify that Ceph-Copper, Datera-Bronze are available
* Verify that kafka-1, kafka-2 and kafka-3 volumes are type Ceph-Copper and
  attached to kafka-1, kafka-2 and kafka-3 servers respectively
* Verify that Kafka is running on all nodes:
    . (on openstack controller node) $ ./kafka_ops.py status 203.0.113.107 --username ubuntu --no-mount
* If kafka is not started on a node run the following:
    . (on openstack controller node) $ ./kafka_ops.py start <node_floating_ip> --username ubuntu -v

* Start the visualizer
    . SSH to 172.19.3.101
    . $ export PATH=$PATH:~/.go/bin
    . $ cd ~/.go/src/github.com/marianogappa/flowbro/
    . $ flowbro
    . Go to http://172.19.3.101:41234/?config=config-3

* Start the loadgenerator
    . SSH to loadgen-1 ([from openstack controller] ip netns exec qrouter-d1da0f92-41b8-40fa-a64f-257bce43992c ssh ubuntu@192.168.20.16)
    . $ source loadgen/bin/activate
    . $ ./kafka_loadgen.py vancouver-demo kafka-1 dev

* The visualizer should be showing messages moving between producers and consumers

Running the Demo
----------------
* Running the demo is simple
    . (on openstack controller node) $ ./kafka_migrator.py kafka-1,kafka-2,kafka-3 kafka-1,kafka-2,kafka-3 Datera-Bronze

* What does this do?
    . It performs the following on each kafka node
        a. Stops kafka on a node
        b. unmounts and detaches the volume from the node
        c. migrates the volume to the new backend/type
        d. attaches the volume and re-mounts it in the node
        e. Starts kafka on the node
