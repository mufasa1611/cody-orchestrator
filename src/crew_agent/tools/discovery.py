from __future__ import annotations

import subprocess
import json
from crewai.tools import BaseTool


class DiscoveryTool(BaseTool):
    name: str = "discover_hosts"
    description: str = (
        "Scan the local network to discover other hosts/devices. "
        "Returns a list of IP addresses and MAC addresses found."
    )

    def _run(self, subnet: str | None = None) -> str:
        # On Windows, we can use Get-NetNeighbor to see local network devices
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-NetNeighbor -AddressFamily IPv4 | "
            "Where-Object { $_.State -ne 'Unreachable' } | "
            "Select-Object IPAddress, LinkLayerAddress, State | "
            "ConvertTo-Json -Compress"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return f"Error running discovery: {result.stderr}"
            
            if not result.stdout.strip():
                return "No neighbors found on the network."
            
            try:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    data = [data]
                
                output = ["Discovered Neighbors:"]
                for item in data:
                    ip = item.get("IPAddress")
                    mac = item.get("LinkLayerAddress")
                    state = item.get("State")
                    output.append(f"- IP: {ip}, MAC: {mac}, State: {state}")
                
                return "\n".join(output)
            except json.JSONDecodeError:
                return f"Raw Output:\n{result.stdout}"
                
        except Exception as e:
            return f"Discovery failed: {e}"
