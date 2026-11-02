import requests
from requests.auth import HTTPDigestAuth
from typing import Dict, Any, Optional

class ShellyPro2PM:
    def __init__(self, ip: str, password: Optional[str] = None):
        self.base_url = f"http://{ip}/rpc"
        # Shelly Gen2/Pro nutzt immer 'admin' als User bei Digest Auth
        self.auth = HTTPDigestAuth("admin", password) if password else None

    def _call_rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/{method}"
        response = requests.post(url, json=params or {}, auth=self.auth, timeout=5)
        response.raise_for_status()
        return response.json()

    def get_channel_status(self, channel: int = 0) -> Dict[str, Any]:
        """
        Returns status and measurements for channel 0 or 1.
        Result contains, among others: output (bool), apower (W), voltage (V), current (A), aenergy (Wh)       
        """
        data = self._call_rpc("Switch.GetStatus", {"id": channel})
        return {
            "channel": channel,
            "is_on": data.get("output", False),
            "power_w": data.get("apower", 0.0),
            "voltage_v": data.get("voltage", 0.0),
            "current_a": data.get("current", 0.0),
            "total_wh": data.get("aenergy", {}).get("total", 0.0),
            "temp_c": data.get("temperature", {}).get("tC", 0.0),
        }

    def set_switch(self, channel: int, on: bool, toggle_after: Optional[int] = None) -> bool:
        """Switch channel 0 or 1 on/off. Optional with timer in seconds."""
        params: Dict[str, Any] = {"id": channel, "on": on}
        if toggle_after is not None:
            params["toggle_after"] = toggle_after
        res = self._call_rpc("Switch.Set", params)
        return res.get("was_on", False)

    def toggle(self, channel: int = 0) -> bool:
        """Toggle the state of channel 0 or 1."""
        res = self._call_rpc("Switch.Toggle", {"id": channel})
        return res.get("was_on", False)

