import csv

def read_ips(path, col_name):
    ips = set()
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ip = row.get(col_name, '-').strip()
            if ip and ip != '-':
                ips.add(ip)
    return ips

base = "Scripts/CT1"

ps_kvm_ch = read_ips(f"{base}/data/CT1_PS_KVM_CH.csv", "Physical IP")
vms = read_ips(f"{base}/data/CT1_VMs.csv", "Virtual Machine IP")
cns = read_ips(f"{base}/data/CT1_CNs.csv", "Container IP")

source_ips = ps_kvm_ch | vms | cns
all_servers = read_ips(f"{base}/CT1_all_servers.csv", "Server IP")

print("PS_KVM_CH unique physical IPs:", len(ps_kvm_ch))
print("VMs unique IPs:", len(vms))
print("CNs unique IPs:", len(cns))
print("Sum (may include overlaps):", len(ps_kvm_ch) + len(vms) + len(cns))
print("Union of source IPs (dedup):", len(source_ips))
print("CT1_all_servers.csv unique IPs:", len(all_servers))

missing_from_all = sorted(source_ips - all_servers)
extra_in_all = sorted(all_servers - source_ips)

with open("missing_from_all_servers.txt", "w") as f:
    f.write("\n".join(missing_from_all) + "\n")

with open("extra_in_all_servers.txt", "w") as f:
    f.write("\n".join(extra_in_all) + "\n")

print("\nIn source files but NOT in all_servers.csv:", len(missing_from_all))
print("In all_servers.csv but NOT in any source file:", len(extra_in_all))

def find_dupes(path, col_name):
    seen = {}
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):
            ip = row.get(col_name, '-').strip()
            if ip and ip != '-':
                seen.setdefault(ip, []).append(i)
    return {ip: lines for ip, lines in seen.items() if len(lines) > 1}

print("\nDuplicate Physical IPs within CT1_PS_KVM_CH.csv:", find_dupes(f"{base}/data/CT1_PS_KVM_CH.csv", "Physical IP"))
print("Duplicate VM IPs within CT1_VMs.csv:", find_dupes(f"{base}/data/CT1_VMs.csv", "Virtual Machine IP"))
print("Duplicate Container IPs within CT1_CNs.csv:", find_dupes(f"{base}/data/CT1_CNs.csv", "Container IP"))
