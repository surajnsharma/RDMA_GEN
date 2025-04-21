#!/bin/bash

set -e

if [ $# -lt 1 ]; then
  echo "Usage: $0 <MFT_PACKAGE_FILENAME.tgz>"
  echo "Example: $0 mft-4.31.0-149-x86_64-deb.tgz"
  exit 1
fi

TARBALL="$1"
PKG_NAME="${TARBALL%.tgz}"
DOWNLOAD_URL="https://content.mellanox.com/mft/${TARBALL}"

if [ ! -f "$TARBALL" ]; then
  echo "Downloading MFT package from:"
  echo "$DOWNLOAD_URL"
  wget "$DOWNLOAD_URL" || { echo "Download failed. Please verify the filename or download it manually."; exit 1; }
else
  echo "Using local file: $TARBALL"
fi

if [ ! -d "$PKG_NAME" ]; then
  tar -xzf "$TARBALL"
fi

cd "$PKG_NAME"
sudo ./install.sh
echo "MFT installed successfully."

echo "Starting mst service..."
sudo mst start

echo ""
echo "Listing Mellanox PCI devices:"
sudo mst status

echo ""
echo "Checking RoCE/DCQCN settings for each device:"
for dev in $(mst status | grep -o '0000:[a-f0-9]*:[a-f0-9]*\\.[0-9]' || true); do
  echo ""
  echo "Device $dev:"
  sudo mlxconfig -d $dev q | grep -Ei 'RoCE|DCQCN|PFC|ECN'
done

echo ""
echo "Validating RDMA environment..."
echo "ibv_devinfo output:"
ibv_devinfo || echo "ibv_devinfo failed"

echo ""
echo "rdma link show:"
rdma link show || echo "rdma link show failed"

echo ""
echo "GID types per Mellanox device:"
for dev in /sys/class/infiniband/*; do
  devname=$(basename "$dev")
  vendor_path="/sys/class/infiniband/$devname/device/vendor"
  if [ -f "$vendor_path" ]; then
    vendor=$(cat "$vendor_path")
    if [ "$vendor" = "0x15b3" ] || [ "$vendor" = "0x02c9" ]; then
      echo "$devname:"
      for f in /sys/class/infiniband/$devname/ports/1/gid_attrs/types/*; do
        if [ -f "$f" ]; then
          index=$(basename "$f")
          current=$(cat "$f" 2>/dev/null || echo "Unreadable")
          echo -n "  GID $index: $current"
          if [ "$current" != "RoCE v2" ]; then
            if [ -w "$f" ]; then
              echo -n " -> Setting to RoCE v2... "
              echo "RoCE v2" | sudo tee "$f" >/dev/null && echo "Success" || echo "Failed"
            else
              echo " -> Skipped (not writable)"
            fi
          else
            echo ""
          fi
        fi
      done
    else
      echo "Skipping non-Mellanox device: $devname"
    fi
  fi
done

echo ""
echo "Firmware versions:"
for dev in $(ibv_devices | awk 'NR>1 {print $1}' | grep -v '\-'); do
  netdir="/sys/class/infiniband/$dev/device/net"
  if [ -d "$netdir" ]; then
    iface=$(ls "$netdir" | head -n1)
    echo -n "$dev ($iface): "
    ethtool -i "$iface" 2>/dev/null | grep -i firmware
  fi
done

echo ""
echo "Validation and GID RoCEv2 fix complete."
