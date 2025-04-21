import os

def read_sysfs(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return "N/A"

def get_rdma_device_interface_mapping():
    base_path = "/sys/class/infiniband"
    debugfs_root = "/sys/kernel/debug/mlx5"
    mapping = {}

    if not os.path.exists(base_path):
        print("No RDMA devices found in /sys/class/infiniband")
        return {}

    for rdma_dev in os.listdir(base_path):
        net_dir = os.path.join(base_path, rdma_dev, "device/net")
        iface_name = "N/A"
        mac_addr = "N/A"
        link_state = "Unknown"
        mtu = "N/A"
        speed_gbps = "N/A"
        roce_mode = "RoCE v1 or IB"
        cnp_received = "N/A"
        dcqcn_enabled = "N/A"
        pci_addr = "N/A"

        if os.path.isdir(net_dir):
            try:
                iface_name = os.listdir(net_dir)[0]
                iface_path = f"/sys/class/net/{iface_name}"

                link_state = read_sysfs(os.path.join(iface_path, "operstate")).upper()
                mtu = read_sysfs(os.path.join(iface_path, "mtu"))
                speed_raw = read_sysfs(os.path.join(iface_path, "speed"))
                speed_gbps = speed_raw if speed_raw != "-1" else "N/A"
                mac_addr = read_sysfs(os.path.join(iface_path, "address"))

                # Detect RoCEv2 by scanning all GID indices
                gid_types_path = os.path.join(base_path, rdma_dev, "ports/1/gid_attrs/types")
                if os.path.isdir(gid_types_path):
                    for gid_file in os.listdir(gid_types_path):
                        gid_type_path = os.path.join(gid_types_path, gid_file)
                        gid_type = read_sysfs(gid_type_path)
                        if gid_type == "RoCE v2":
                            roce_mode = "RoCE v2"
                            break

                # Get PCI address
                try:
                    pci_link = os.path.realpath(os.path.join(base_path, rdma_dev, "device"))
                    pci_addr = os.path.basename(pci_link)
                except Exception:
                    pci_addr = "N/A"

                # If RoCEv2 is active and interface is UP, check CNP/DCQCN
                if link_state == "UP" and roce_mode == "RoCE v2":
                    ethtool_output = os.popen(f"ethtool -S {iface_name} 2>/dev/null | grep -i cnp").read()
                    cnp_received = "Yes" if "cnp" in ethtool_output.lower() else "No"

                    # Detect DCQCN model
                    cc_params_path = os.path.join(debugfs_root, pci_addr, "cc_params")
                    if os.path.isdir(cc_params_path):
                        expected_fields = ["rp_dce_tcp_g", "rp_threshold", "rp_clamp_tgt_rate"]
                        available = all(os.path.exists(os.path.join(cc_params_path, f)) for f in expected_fields)
                        dcqcn_enabled = "Yes" if available else "Partial"
                    elif os.path.isfile(cc_params_path):
                        cc_params = read_sysfs(cc_params_path)
                        dcqcn_enabled = "Yes" if "ecn_en: 1" in cc_params else "No"
                    else:
                        dcqcn_enabled = "Not Found"

            except Exception:
                pass

        mapping[rdma_dev] = {
            "interface": iface_name,
            "mac": mac_addr,
            "link_state": link_state,
            "mtu": mtu,
            "speed_gbps": speed_gbps,
            "roce_mode": roce_mode,
            "cnp_received": cnp_received,
            "dcqcn_enabled": dcqcn_enabled,
            "pci_addr": pci_addr
        }

    return mapping


if __name__ == "__main__":
    rdma_map = get_rdma_device_interface_mapping()
    header = f"{'RDMA Dev':<15} {'Interface':<15} {'MAC Addr':<18} {'Link':<8} {'MTU':<6} {'Speed':<8} {'RoCE Mode':<15} {'CNP':<6} {'DCQCN':<9} {'PCI Addr'}"
    print(header)
    print("-" * len(header))
    for dev, info in rdma_map.items():
        print(f"{dev:<15} {info['interface']:<15} {info['mac']:<18} {info['link_state']:<8} {info['mtu']:<6} {info['speed_gbps']:<8} "
              f"{info['roce_mode']:<15} {info['cnp_received']:<6} {info['dcqcn_enabled']:<9} {info['pci_addr']}")
