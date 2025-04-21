#!/usr/bin/env python3

import os
import subprocess
import re
from shutil import copyfile

HUGEPAGES = 1024
HUGEPAGE_MOUNT = "/mnt/huge"

def run(cmd):
    print(f"[RUN] {cmd}")
    subprocess.run(cmd, shell=True, check=True)

def install_packages():
    packages = [
        "git", "build-essential", "python3-pip",
        "libnuma-dev", "libibverbs-dev", "rdma-core",
        "ibverbs-utils", "pciutils", "ethtool"
    ]
    run(f"apt-get update && apt-get install -y {' '.join(packages)}")
    run("pip3 install --upgrade pip")
    run("pip3 install prometheus_client")

def configure_hugepages():
    print("Configuring hugepages and mounting hugetlbfs")
    run(f"mkdir -p {HUGEPAGE_MOUNT}")
    run(f"mount -t hugetlbfs nodev {HUGEPAGE_MOUNT}")
    with open("/etc/sysctl.d/99-hugepages.conf", "w") as f:
        f.write(f"vm.nr_hugepages = {HUGEPAGES}\n")
    run("sysctl -p")

def persist_hugepages_systemd():
    print("Creating systemd mount for hugepages")
    mount_unit = "/etc/systemd/system/mnt-huge.mount"
    with open(mount_unit, "w") as f:
        f.write(f"""[Unit]
Description=Hugepages Mount

[Mount]
What=hugetlbfs
Where={HUGEPAGE_MOUNT}
Type=hugetlbfs
Options=pagesize=2M

[Install]
WantedBy=multi-user.target
""")
    run("systemctl daemon-reexec")
    run("systemctl enable --now mnt-huge.mount")

def update_grub_for_hugepages():
    print("Updating GRUB for hugepages and IOMMU settings")
    grub_file = "/etc/default/grub"
    backup_file = "/etc/default/grub.bak"
    copyfile(grub_file, backup_file)

    with open(grub_file, "r") as f:
        lines = f.readlines()

    new_lines = []
    found = False
    append_args = "default_hugepagesz=2M hugepagesz=2M hugepages=1024 iommu=pt intel_iommu=on"

    for line in lines:
        if line.strip().startswith("GRUB_CMDLINE_LINUX"):
            found = True
            match = re.match(r'GRUB_CMDLINE_LINUX="(.*)"', line.strip())
            if match:
                existing_args = match.group(1)
                if append_args not in existing_args:
                    updated_args = existing_args + " " + append_args
                else:
                    updated_args = existing_args
                new_lines.append(f'GRUB_CMDLINE_LINUX="{updated_args.strip()}"\n')
            else:
                print("Invalid GRUB_CMDLINE_LINUX line format. Restoring from backup.")
                copyfile(backup_file, grub_file)
                return
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f'GRUB_CMDLINE_LINUX="{append_args}"\n')

    with open(grub_file, "w") as f:
        f.writelines(new_lines)

    run("update-grub")

def main():
    install_packages()
    configure_hugepages()
    persist_hugepages_systemd()
    update_grub_for_hugepages()

    print("\nInstallation complete.")
    print("Please reboot the system to apply GRUB and hugepage changes.\n")

if __name__ == "__main__":
    main()
