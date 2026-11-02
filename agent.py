import asyncio
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aiohttp import ClientError, ClientSession
from dotenv import load_dotenv
from requests import RequestException
from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from anker_solix_api.api import AnkerSolixApi
from anker_solix_api.errors import AnkerSolixError
from shelly import ShellyPro2PM

SHELLY_CHANNEL                      = 1                 # channel where SHELLY is connected
SHELLY_HOST                         = "192.168.1.9"     # SHELLY host IP address

BATTERY_LEVEL_FOR_HOME_OUTPUT       = 7                # battery level threshold in percent for home output 
POLL_INTERVAL_SECONDS               = 60
DEVICE_DETAILS_INTERVAL_SECONDS     = 15 * 60
SOLARBANK_PRO_MODEL                 = "A17C1"

console = Console()
logger = logging.getLogger("solarbank-agent")


@dataclass(frozen=True)
class SolarbankReading:
    site_name: str
    device_name: str
    soc: float | None
    solar_power: float | None
    home_output: float | None
    grid_import: float | None
    grid_export: float | None


@dataclass(frozen=True)
class ShellyChannelReading:
    channel: int
    is_on: bool
    power_w: float
    voltage_v: float
    current_a: float
    total_kwh: float
    temp_c: float


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip().removesuffix("W").strip())
    except (TypeError, ValueError):
        return None


def _first_number(*values: object) -> float | None:
    for value in values:
        parsed = _number(value)
        if parsed is not None:
            return parsed
    return None


def _grid_readings(
    site: Mapping[str, Any], devices: Mapping[str, Any]
) -> tuple[float | None, float | None]:
    grid_info = _mapping(site.get("grid_info"))
    signed_readings: list[float] = []

    for meter in grid_info.get("grid_list") or []:
        meter = _mapping(meter)
        device = _mapping(devices.get(str(meter.get("device_sn", ""))))
        mqtt_data = _mapping(device.get("mqtt_data"))
        signed = _first_number(
            mqtt_data.get("grid_power_signed"),
            device.get("grid_power_signed"),
        )
        if signed is not None:
            signed_readings.append(signed)

    if signed_readings:
        signed_power = sum(signed_readings)
        return max(signed_power, 0), max(-signed_power, 0)

    return (
        _number(grid_info.get("grid_to_home_power")),
        _number(grid_info.get("photovoltaic_to_grid_power")),
    )


def collect_readings(
    sites: Mapping[str, Any], devices: Mapping[str, Any]
) -> list[SolarbankReading]:
    readings: list[SolarbankReading] = []

    for site_id, raw_site in sites.items():
        site = _mapping(raw_site)
        site_info = _mapping(site.get("site_info"))
        solarbank_info = _mapping(site.get("solarbank_info"))
        solarbanks = solarbank_info.get("solarbank_list") or []
        grid_import, grid_export = _grid_readings(site, devices)
        site_name = str(site_info.get("site_name") or site_id)

        for raw_bank in solarbanks:
            bank = _mapping(raw_bank)
            serial = str(bank.get("device_sn") or "")
            device = _mapping(devices.get(serial))
            model = str(
                bank.get("device_pn")
                or device.get("device_pn")
                or device.get("product_code")
                or ""
            )
            device_name = str(
                bank.get("device_name") or device.get("alias") or model or serial
            )
            if (
                model != SOLARBANK_PRO_MODEL
                and "solarbank 2 e1600 pro" not in device_name.lower()
            ):
                continue

            pv_values: list[float] = []
            raw_pv = _mapping(bank.get("pv_power"))
            for index in range(1, 5):
                channel = _first_number(
                    device.get(f"solar_power_{index}"),
                    bank.get(f"solar_power_{index}"),
                    raw_pv.get(f"pv{index}"),
                )
                if channel is not None:
                    pv_values.append(channel)
            solar_power = (
                sum(pv_values)
                if pv_values
                else _first_number(
                    device.get("input_power"),
                    bank.get("photovoltaic_power"),
                    solarbank_info.get("total_photovoltaic_power"),
                )
            )

            readings.append(
                SolarbankReading(
                    site_name=site_name,
                    device_name=device_name,
                    soc=_first_number(
                        device.get("battery_soc"),
                        bank.get("battery_power"),
                        bank.get("bat_soc"),
                        solarbank_info.get("total_bat_soc"),
                    ),
                    solar_power=solar_power,
                    home_output=_first_number(
                        device.get("to_home_load"),
                        bank.get("output_power"),
                        solarbank_info.get("to_home_load"),
                        solarbank_info.get("total_output_power"),
                    ),
                    grid_import=grid_import,
                    grid_export=grid_export,
                )
            )

    return readings


def _format_power(value: float | None) -> str:
    return "Not available" if value is None else f"{value:,.0f} W"


def _format_soc(value: float | None) -> str:
    return "Not available" if value is None else f"{value:.0f} %"


def control_shelly(shelly: ShellyPro2PM) -> list[ShellyChannelReading]:
    readings: list[ShellyChannelReading] = []
    for channel in (0, 1):
        status_changed = False
        status = shelly.get_channel_status(channel)

        # check if change of state necessary
        if SHELLY_CHANNEL == channel:
            if not bool(status["is_on"]):
                # Boiler has no power
                logger.info("Shelly switch state changed to ON.")
                status_changed = True
                shelly.set_switch(channel, True)
            else:
                # Boiler has power
                logger.info("Shelly switch state changed to OFF.")
                status_changed = True
                shelly.set_switch(channel, False)

            if status_changed:
                status = shelly.get_channel_status(channel)

        # update info
        readings.append(
            ShellyChannelReading(
                channel=channel,
                is_on=bool(status["is_on"]),
                power_w=float(status["power_w"]),
                voltage_v=float(status["voltage_v"]),
                current_a=float(status["current_a"]),
                total_kwh=float(status["total_wh"]) / 1000,
                temp_c=float(status["temp_c"]),
            )
        )

    return readings


def make_shelly_table(
    channels: list[ShellyChannelReading], error: str | None
) -> Table:
    table = Table(box=box.SIMPLE_HEAVY, expand=True, title="Shelly Pro 2PM")
    table.add_column("Channel")
    table.add_column("State")
    table.add_column("Power")
    table.add_column("Voltage")
    table.add_column("Current")
    table.add_column("Energy")
    table.add_column("Temperature")

    if channels:
        color = "grey50"
        for channel in channels:
            if SHELLY_CHANNEL == channel.channel:
                color = "green" if channel.is_on else "red"

            table.add_row(
                f"[{color}]{str(channel.channel)}[/{color}]",
                f"[{color}]{'ON' if channel.is_on else 'OFF'}[/{color}]",
                f"[{color}]{_format_power(channel.power_w)}[/{color}]",
                f"[{color}]{channel.voltage_v:.1f} V[/{color}]",
                f"[{color}]{channel.current_a:.2f} A[/{color}]",
                f"[{color}]{channel.total_kwh:.2f} kWh[/{color}]",
                f"[{color}]{channel.temp_c:.1f} °C[/{color}]",
            )
    else:
        table.add_row(
            "—",
            "[red]Unreachable[/red]" if error else "No data yet",
            "—",
            "—",
            "—",
            "—",
            "—",
        )
    return table


def make_dashboard(
    readings: list[SolarbankReading],
    shelly_channels: list[ShellyChannelReading],
    last_updated: datetime | None,
    last_error: str | None,
    shelly_error: str | None,
) -> Panel:
    table = Table(box=box.SIMPLE_HEAVY, expand=True, title="Anker Solarbank 2 E1600 Pro")
    table.add_column("Battery")
    table.add_column("Solar Input")
    table.add_column("Home Output")
    table.add_column("Grid Import")
    table.add_column("Grid Export")

    if readings:
        for reading in readings:
            if (reading.home_output is not None) and (reading.home_output > 0):
                color = "green"
            else:
                color = "red"

            table.add_row(
                f"[{color}]{_format_soc(reading.soc)}[/{color}]",
                f"[{color}]{_format_power(reading.solar_power)}[/{color}]",
                f"[{color}]{_format_power(reading.home_output)}[/{color}]",
                f"[{color}]{_format_power(reading.grid_import)}[/{color}]",
                f"[{color}]{_format_power(reading.grid_export)}[/{color}]",
            )
    else:
        table.add_row(
            "—",
            "—",
            "—",
            "—",
            "—",
        )

    timestamp = (
        last_updated.strftime("%Y-%m-%d %H:%M:%S")
        if last_updated
        else "No successful location data yet"
    )
    status = f"Last update: {timestamp}"
    if last_error:
        status += f"\n[red]Last error: {last_error}[/red]"
    if shelly_error:
        status += f"\n[red]Shelly error: {shelly_error}[/red]"

    return Panel(
        Group(table, make_shelly_table(shelly_channels, shelly_error), status),
        title="Balkonkraftwerk - Control",
        border_style="green" if not (last_error or shelly_error) else "red",
    )


async def run_agent() -> None:
    load_dotenv()
    email = os.getenv("ANKER_USER")
    password = os.getenv("ANKER_PASSWORD")
    country = os.getenv("ANKER_COUNTRY", "AT")
    if not email or not password:
        raise RuntimeError(
            "ANKER_USER and ANKER_PASSWORD must be set in the .env file."
        )
    shelly = ShellyPro2PM(
        ip=os.getenv("SHELLY_HOST", SHELLY_HOST),
        password=os.getenv("SHELLY_PASSWORD") or None,
    )

    async with ClientSession() as websession:
        api = AnkerSolixApi(
            email=email,
            password=password,
            countryId=country,
            websession=websession,
        )
        loop = asyncio.get_running_loop()
        next_device_details = 0.0
        readings: list[SolarbankReading] = []
        shelly_channels: list[ShellyChannelReading] = []
        last_updated: datetime | None = None
        last_error: str | None = None
        shelly_error: str | None = None

        with Live(
            make_dashboard(
                readings, shelly_channels, last_updated, last_error, shelly_error
            ),
            console=console,
            refresh_per_second=1,
        ) as live:
            while True:
                poll_started = loop.time()
                try:
                    await api.update_sites()
                    readings = collect_readings(api.sites, api.devices)
                    last_updated = datetime.now().astimezone()
                    last_error = None
                    logger.info("Location and data update done.")
                except (AnkerSolixError, ClientError, TimeoutError) as error:
                    last_error = f"{type(error).__name__}: {error}"
                    logger.error("Anker query failed: %s", last_error)

                if poll_started >= next_device_details:
                    next_device_details = (
                        loop.time() + DEVICE_DETAILS_INTERVAL_SECONDS
                    )
                    try:
                        await api.update_device_details()
                    except (AnkerSolixError, ClientError, TimeoutError) as error:
                        last_error = f"{type(error).__name__}: {error}"
                        logger.error(
                            "Device details could not be updated: %s",
                            last_error,
                        )

                try:
                    # the Shelly client is blocking, keep it off the event loop
                    shelly_channels = await asyncio.to_thread(control_shelly, shelly)
                    shelly_error = None
                except (RequestException, KeyError, ValueError) as error:
                    shelly_error = f"{type(error).__name__}: {error}"
                    logger.error("Shelly query failed: %s", shelly_error)

                live.update(
                    make_dashboard(
                        readings,
                        shelly_channels,
                        last_updated,
                        last_error,
                        shelly_error,
                    )
                )
                await asyncio.sleep(
                    max(
                        0,
                        POLL_INTERVAL_SECONDS - (loop.time() - poll_started),
                    )
                )


def main() -> None:   
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )

    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        logger.info("Agent stopped.")


if __name__ == "__main__":
    main()
