cat << 'EOF' > /tmp/setup-vpn-dns.sh
#!/bin/bash
set -euo pipefail

echo "=== 1. Dynamically Detecting WAN Interface ==="
WAN_IFACE=$(ip -4 route show default 2>/dev/null | awk '/default/ {print $5}' | head -n1)
WAN_IFACE=${WAN_IFACE:-enp1s0}
echo "[+] Detected primary WAN interface: $WAN_IFACE"

echo "=== 2. Installing Dependencies ==="
apt-get update
apt-get install -y dnsmasq iproute2

echo "=== 3. Handling systemd-resolved while preserving upstream DNS ==="
# Extract existing upstream nameservers before disabling systemd-resolved
UPSTREAM_DNS=$(grep -h '^nameserver' /run/systemd/resolve/resolv.conf /etc/resolv.conf 2>/dev/null | grep -v '127.0.0.53' | sort -u || true)

# Stop systemd-resolved from holding port 53
if systemctl is-active --quiet systemd-resolved 2>/dev/null; then
    systemctl stop systemd-resolved
    systemctl disable systemd-resolved
fi

# Replace the symlink with a clean resolv.conf
rm -f /etc/resolv.conf
if [ -n "$UPSTREAM_DNS" ]; then
    cat <<< "$UPSTREAM_DNS" > /etc/resolv.conf
else
    cat << 'RES' > /etc/resolv.conf
nameserver 1.1.1.1
nameserver 8.8.8.8
RES
fi

# Inhibit resolvconf override behavior in Debian
cat << 'DEF' > /etc/default/dnsmasq
IGNORE_RESOLVCONF=yes
DNSMASQ_EXCEPT="lo"
DEF

echo "=== 4. Creating Persistent VPN DNS Gateway IP Service ==="
cat << 'IPSERVICE' > /etc/systemd/system/vpn-dns-ip.service
[Unit]
Description=Bind VPN DNS Gateway IP to Loopback
Before=dnsmasq.service network.target
DefaultDependencies=no

[Service]
Type=oneshot
ExecStart=/bin/sh -c '/sbin/ip addr show dev lo | grep -q "10.2.0.1" || /sbin/ip addr add 10.2.0.1/32 dev lo'
RemainAfterExit=yes

[Install]
WantedBy=sysinit.target
IPSERVICE

systemctl daemon-reload
systemctl enable vpn-dns-ip.service
systemctl restart vpn-dns-ip.service

echo "=== 5. Writing dnsmasq Split-Horizon Configuration ==="
rm -f /etc/dnsmasq.d/*

cat << DNSCONF > /etc/dnsmasq.d/l2tp-vpn.conf
# Bind dynamically to handle ppp interfaces as clients connect
bind-dynamic
listen-address=127.0.0.1,10.2.0.1
except-interface=$WAN_IFACE
resolv-file=/etc/resolv.conf
domain-needed
bogus-priv
address=/appserver.tarrantadvisors.com/10.2.0.1
DNSCONF

echo "=== 6. Bypassing Debian's --local-service via systemd Override ==="
mkdir -p /etc/systemd/system/dnsmasq.service.d/

cat << 'OVERRIDE' > /etc/systemd/system/dnsmasq.service.d/override.conf
[Unit]
After=network.target vpn-dns-ip.service
Requires=vpn-dns-ip.service

[Service]
ExecStart=
ExecStart=/usr/sbin/dnsmasq -x /run/dnsmasq/dnsmasq.pid -u dnsmasq -7 /etc/dnsmasq.d,.dpkg-dist,.dpkg-old,.dpkg-new
Restart=on-failure
RestartSec=3s
OVERRIDE

systemctl daemon-reload
systemctl restart dnsmasq
systemctl enable dnsmasq

echo "=== 7. Updating PPP Configuration to Push 10.2.0.1 ==="
for PPP_FILE in /etc/ppp/options /etc/ppp/options.xl2tpd; do
    if [ -f "$PPP_FILE" ]; then
        sed -i '/ms-dns/d' "$PPP_FILE"
        echo "ms-dns 10.2.0.1" >> "$PPP_FILE"
    fi
done

if systemctl is-active --quiet xl2tpd 2>/dev/null; then
    systemctl restart xl2tpd
fi

echo "=== 8. Verification Check ==="
echo -n "Checking if 10.2.0.1:53 is actively listening... "
if ss -tuln | grep -q '10.2.0.1:53'; then
    echo "SUCCESS!"
else
    echo "FAILED! 10.2.0.1:53 is not open."
    exit 1
fi

echo "Checking if --local-service was safely stripped... "
if ps aux | grep [d]nsmasq | grep -q '\--local-service'; then
    echo "FAILED! --local-service is still active."
    exit 1
else
    echo "SUCCESS!"
fi

echo "=== SCRIPT COMPLETE ==="
EOF

chmod +x /tmp/setup-vpn-dns.sh
/tmp/setup-vpn-dns.sh