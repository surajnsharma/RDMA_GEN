#!/bin/bash

set -e

IFACE="$1"
if [[ -z "$IFACE" ]]; then
  echo "Usage: $0 <interface-name>"
  exit 1
fi

echo "Configuring RoCEv2 + DCQCN on interface: $IFACE"

# Validate interface
if ! ip link show "$IFACE" &> /dev/null; then
  echo "Error: Interface $IFACE not found"
  exit 2
fi

# Get PCI address
PCI=$(ethtool -i "$IFACE" | awk '/bus-info/ {print $2}')
if [[ -z "$PCI" ]]; then
  echo "Error: Could not determine PCI address for $IFACE"
  exit 3
fi

echo "Note: Skipping DCQCN via mlxconfig (not applicable for ConnectX-7)"

# Map to RDMA device
RDMA_DEV=""
for dev in /sys/class/infiniband/*; do
  for netdev in "$dev/device/net/"*; do
    if [[ "$(basename "$netdev")" == "$IFACE" ]]; then
      RDMA_DEV=$(basename "$dev")
      break 2
    fi
  done
done

if [[ -z "$RDMA_DEV" ]]; then
  echo "Error: Could not map $IFACE to an RDMA device"
  exit 4
fi

# Attempt to set GID index 0 to RoCE v2 if allowed
GID_FILE="/sys/class/infiniband/$RDMA_DEV/ports/1/gid_attrs/types/0"
if [[ -w "$GID_FILE" ]]; then
  echo "Setting GID index 0 to RoCE v2 for $RDMA_DEV ($IFACE)"
  echo "RoCE v2" | sudo tee "$GID_FILE" > /dev/null

  RESULT=$(cat "$GID_FILE")
  if [[ "$RESULT" == "RoCE v2" ]]; then
    echo "Confirmed: GID 0 set to RoCE v2"
  else
    echo "Warning: Tried to set RoCE v2, but value is: $RESULT"
  fi
else
  echo "Notice: GID file $GID_FILE is read-only. Skipping manual override (firmware-managed)."
fi

# Install lldpad if needed
if ! command -v dcbtool &> /dev/null; then
  echo "Installing lldpad package (provides dcbtool)..."
  if [[ -f /etc/debian_version ]]; then
    sudo apt update
    sudo apt install -y lldpad
  elif [[ -f /etc/redhat-release ]]; then
    sudo yum install -y lldpad
  else
    echo "Unsupported OS. Please install 'lldpad' manually."
    exit 5
  fi
fi

# Start lldpad if not running
if ! pgrep -x lldpad &> /dev/null; then
  echo "Starting lldpad service..."
  sudo systemctl enable lldpad
  sudo systemctl start lldpad
fi

# Apply PFC + ECN configuration
echo "Applying PFC and ECN settings to $IFACE (priority 3)"
sudo dcbtool sc "$IFACE" pfc e:1 a:1 w:1 > /dev/null
sudo dcbtool sc "$IFACE" app:udp:4791 > /dev/null

# Enable ECN in cc_params if available
CC_PARAMS="/sys/kernel/debug/mlx5/${PCI}/cc_params"
if [[ -f "$CC_PARAMS" ]]; then
  echo "Enabling ECN in $CC_PARAMS"
  echo "ecn_en: 1" | sudo tee "$CC_PARAMS" > /dev/null
else
  echo "Note: $CC_PARAMS not found. Skipping ECN config."
fi

# Final GID type summary
echo "GID types for $RDMA_DEV:"
cat /sys/class/infiniband/$RDMA_DEV/ports/1/gid_attrs/types/* | sort | uniq

echo "Configuration complete for $IFACE"