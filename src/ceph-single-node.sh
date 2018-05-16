#!/bin/bash -xe

# Requires Node with the following attributes:
# 2 GB RAM
# 2 VCPUs
# 2 interfaces (ens3 MGMT and ens4 ANYTHING)
# Hostame == ${NAME}
# vdb >= 1 TB
# vdc >= 1 TB
# vdd >= 1 TB
if [[ "$@" -lt 3 ]]; then
    echo "Usage: $0 hostname iface device1 device2 ..."
    exit 1
fi

NAME=$1
IFACE=$2
shift
shift
DEVS="$@"

echo "Creating single-node Ceph cluster"
echo "Hostname: $NAME"
echo "Devices: $DEVS"

for bd in ${DEVS[@]}; do
    if ! [ -b $bd ]; then
        echo "Need block device ${bd}"
        exit 1
    fi
done

export IP="$(sudo ifconfig ${IFACE} | grep "inet addr" | cut -d ":" -f 2 | cut -d " " -f 1)"

# Add hostname to /etc/hosts if it's not already there

if [[ "$(cat /etc/hosts | grep $NAME)" == "" ]]; then
    cmd="${IP} ${NAME}\n$(cat /etc/hosts)"
    sudo -E sh -c "echo \"${cmd}\" > /etc/hosts"
fi

# Install Ceph prereqs
wget -q -O- "https://download.ceph.com/keys/release.asc" | sudo apt-key add -
echo deb http://download.ceph.com/debian-jewel/ xenial main | sudo tee /etc/apt/sources.list.d/ceph.list
sudo apt-get update && sudo apt-get install ceph-deploy -y

# Setup ceph-deploy user if it doesn't exist
if [[ $(cut -d: -f1 "/etc/passwd" | grep "ceph-deploy") == "" ]]; then
    sudo useradd -m -s /bin/bash ceph-deploy
    sudo passwd ceph-deploy
    echo "ceph-deploy ALL = (root) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/ceph-deploy
    sudo chmod 0440 /etc/sudoers.d/ceph-deploy
fi

# Generate ssh keyfiles and register on same node
if ! [ -e /home/ceph-deploy/.ssh/id_rsa.pub ]; then
    sudo su ceph-deploy -c "ssh-keygen"
    sudo su ceph-deploy -c "cat ~/.ssh/id_rsa.pub >> ~/.ssh/authorized_keys"
    sudo su ceph-deploy -c "ssh-copy-id ceph-deploy@${NAME}"
fi

# Make directory for cluster configs
if ! [ -e /home/ceph-deploy/my-cluster ]; then
    sudo su ceph-deploy -c "cd ~ && mkdir ~/my-cluster"
fi

# Create the new config
sudo su ceph-deploy -c "cd ~/my-cluster && ceph-deploy new ${NAME}"

# Set single-node params
sudo sh -c "echo 'osd_pool_default_size = 1' >> /home/ceph-deploy/my-cluster/ceph.conf"
sudo sh -c "echo 'osd_crush_chooseleaf_type = 0' >> /home/ceph-deploy/my-cluster/ceph.conf"

# Install Ceph
sudo su ceph-deploy -c "cd ~/my-cluster && ceph-deploy install ${NAME}"

# Create monitor service
sudo su ceph-deploy -c "cd ~/my-cluster && ceph-deploy mon create-initial"

# Configure block device daemons
for bd in ${DEVS[@]}; do
    sudo su ceph-deploy -c "cd ~/my-cluster && ceph-deploy osd prepare ${NAME}:${bd}"
done

# Activate block device daemons
for bd in ${DEVS[@]}; do
    sudo su ceph-deploy -c "cd ~/my-cluster && ceph-deploy osd activate ${NAME}:${bd}1"
done

# Create admin user
sudo su ceph-deploy -c "cd ~/my-cluster && ceph-deploy admin ${NAME}"
sudo su ceph-deploy -c "cd ~/my-cluster && sudo chmod +r /etc/ceph/ceph.client.admin.keyring"

# Print status
sudo su ceph-deploy -c "cd ~/my-cluster && ceph -s"

echo "Waiting for Ceph cluster to form"
sleep 10

# Create storage gateway and cephfs
sudo su ceph-deploy -c "cd ~/my-cluster && ceph-deploy rgw create ${NAME}"
sudo su ceph-deploy -c "cd ~/my-cluster && ceph-deploy mds create ${NAME}"

# Setup cephfs volumes
sudo su ceph-deploy -c "cd ~/my-cluster && ceph osd pool create cephfs_data 128"
sudo su ceph-deploy -c "cd ~/my-cluster && ceph osd pool create cephfs_metadata 128"

# Create filesystem
sudo su ceph-deploy -c "cd ~/my-cluster && ceph fs new cephfs cephfs_metadata cephfs_data"

# Ceph client libraries
sudo apt-get install ceph-fs-common -y

# Mount cephfs filesystem
sudo mkdir /mnt/mycephfs
SKEY=sudo su ceph-deploy -c "cat ~/my-cluster/ceph.client.admin.keyring" | grep key | awk '{print $3}'
sudo mount -t ceph ${NAME}:6789:/ /mnt/mycephfs -o name=admin,secret=${SKEY}

# Show mount
df -h /mnt/mycephfs
