from __future__ import annotations

import subprocess
import json
from crewai.tools import BaseTool


class DiscoveryTool(BaseTool):
    name: str = "discover_hosts"
    description: str = (
        "Scan the local network to discover other hosts and attempt to identify their OS. "
        "Returns a list of IP addresses, MAC addresses, and OS hints."
    )

    def _run(self, subnet: str | None = None) -> str:
        # 1. Get neighbors from ARP cache
        arp_cmd = ["powershell.exe", "-NoProfile", "-Command", 
                   "Get-NetNeighbor -AddressFamily IPv4 | Where-Object { $_.State -ne 'Unreachable' } | Select-Object IPAddress, LinkLayerAddress | ConvertTo-Json -Compress"]
        
        try:
            arp_result = subprocess.run(arp_cmd, capture_output=True, text=True, timeout=15)
            neighbors = []
            if arp_result.returncode == 0 and arp_result.stdout.strip():
                data = json.loads(arp_result.stdout)
                neighbors = data if isinstance(data, list) else [data]

            if not neighbors:
                return "No devices found in local ARP cache."

            output = ["Discovered Infrastructure:"]
            for n in neighbors[:10]: # Limit to first 10 for speed
                ip = n.get("IPAddress")
                mac = n.get("LinkLayerAddress")
                
                # 2. Attempt OS Fingerprinting via TTL (simple but fast)
                # TTL 128 = Windows, TTL 64 = Linux/Mac
                ping_cmd = ["ping", "-n", "1", "-w", "500", ip]
                ping_proc = subprocess.run(ping_cmd, capture_output=True, text=True)
                os_hint = "Unknown"
                if "TTL=128" in ping_proc.stdout:
                    os_hint = "Windows"
                elif "TTL=64" in ping_proc.stdout:
                    os_hint = "Linux/Unix"
                
                output.append(f"- IP: {ip} | MAC: {mac} | OS Hint: {os_hint}")
            
            return "\n".join(output)
                
        except Exception as e:
            return f"Discovery failed: {e}"
