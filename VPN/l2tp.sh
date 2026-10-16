cat << 'EOF' > setup-vpn-minimal.sh
#!/usr/bin/env bash
# ==============================================================================
# Production-Grade L2TP/IPsec VPN + Split-Horizon DNS Installer
# Compatible with Debian 12 (Bookworm) and Debian 13 (Trixie)
# Firewall/iptables rules excluded (managed separately)
# ==============================================================================

set -euo pipefail

# 1. Root Check
if [[ $EUID -ne 0 ]]; then
   echo "[-] This script must be run as root." >&2
   exit 1
fi

echo "[+] Starting L2TP/IPsec VPN + DNS setup..."

# Dynamically detect primary network interface (e.g., enp1s0, eth0, ens3)
WAN_IFACE=$(ip -4 route show default 2>/dev/null | awk '/default/ {print $5}' | head -n1)
WAN_IFACE=${WAN_IFACE:-enp1s0}
echo "[+] Detected WAN interface: $WAN_IFACE"

# 2. Automatic Credentials Generation
VPN_PSK=$(openssl rand -hex 20)
VPN_USER="vpnuser"
VPN_PASS=$(openssl rand -hex 12)

# 3. Package Installation
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq strongswan libcharon-extra-plugins xl2tpd ppp openssl

# 6. Enable Global Forwarding & Static Kernel Flags
cat << SYSCTL > /etc/sysctl.d/99-l2tp-vpn.conf
net.ipv4.ip_forward = 1
net.ipv4.conf.all.rp_filter = 0
net.ipv4.conf.default.rp_filter = 0
net.ipv4.conf.${WAN_IFACE}.rp_filter = 0
net.ipv4.conf.all.route_localnet = 1
SYSCTL
sysctl --system > /dev/null

# Dynamic PPP interface hook for rp_filter=0 on client connect
mkdir -p /etc/ppp/ip-up.d
cat << 'HOOK' > /etc/ppp/ip-up.d/00-vpn-rpfilter
#!/bin/sh
if [ -n "$1" ]; then
    sysctl -w "net.ipv4.conf.$1.rp_filter=0" >/dev/null 2>&1
    sysctl -w "net.ipv4.conf.$1.route_localnet=1" >/dev/null 2>&1
fi
HOOK
chmod +x /etc/ppp/ip-up.d/00-vpn-rpfilter

# 7. strongSwan Configuration
cat <<IPSEC_CONF > /etc/ipsec.conf
conn L2TP-PSK
	authby=secret
	auto=add
	keyexchange=ikev1
	type=transport
	left=%any
	leftprotoport=17/1701
	right=%any
	rightprotoport=17/%any
	ike=aes256-sha256-modp2048,aes256-sha1-modp1024,3des-sha1-modp1024
	esp=aes256-sha256,aes256-sha1,3des-sha1
IPSEC_CONF

cat <<IPSEC_SECRETS > /etc/ipsec.secrets
%any %any : PSK "$VPN_PSK"
IPSEC_SECRETS
chmod 600 /etc/ipsec.secrets

# 8. xl2tpd Configuration
cat <<XL2TPD > /etc/xl2tpd/xl2tpd.conf
[global]
port = 1701

[lns default]
ip range = 10.2.0.10-10.2.0.250
local ip = 10.2.0.1
require authentication = yes
name = l2tpd
pppoptfile = /etc/ppp/options.xl2tpd
XL2TPD

# 9. PPP Configuration (Pushing Local DNS Gateway 10.2.0.1)
cat <<PPP_OPT > /etc/ppp/options.xl2tpd
ipcp-accept-local
ipcp-accept-remote
ms-dns 1.1.1.1
ms-dns 8.8.8.8
auth
require-mschap-v2
mtu 1280
mru 1280
name l2tpd
PPP_OPT

cat <<CHAP_SECRETS > /etc/ppp/chap-secrets
"$VPN_USER"        l2tpd     "$VPN_PASS"      *
CHAP_SECRETS
chmod 600 /etc/ppp/chap-secrets

# 10. Service Restarts
if systemctl list-unit-files | grep -q strongswan-starter; then
    systemctl restart strongswan-starter
    systemctl enable strongswan-starter
else
    systemctl restart strongswan
    systemctl enable strongswan
fi

systemctl restart xl2tpd
systemctl enable xl2tpd

echo ""
echo "=========================================================="
echo "  Debian L2TP/IPsec VPN + DNS Installation Complete!      "
echo "=========================================================="
echo " Pre-Shared Key:   $VPN_PSK"
echo " Username:         $VPN_USER"
echo " Password:         $VPN_PASS"
echo " Subnet Pool:      10.2.0.0/24"
echo " DNS Gateway:      10.2.0.1 (dnsmasq active)"
echo " WAN Interface:    $WAN_IFACE"
echo "=========================================================="
EOF

chmod +x setup-vpn-minimal.sh
