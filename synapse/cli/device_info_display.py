from rich.console import Console
from rich.tree import Tree
from google.protobuf.json_format import MessageToDict
from synapse.client.device import Device


def visualize_configuration(info_dict, status):
    nodes_status = status.get("signal_chain", {}).get("nodes", {})
    config = info_dict.get("configuration", {})
    if config:
        tree = Tree("Configuration")
        for index, node in enumerate(config.get("nodes", [])):
            node_type = node.get("type", "").replace("k", "")
            node_tree = tree.add(f"{node_type}")
            node_tree.add(f"ID: {node.get('id', 'Unknown')}")
            if node_type == "Application":
                app = node.get("application", {})
                name = app.get("name", "Unknown")

                application_status = nodes_status[index].get("application", None)
                running = application_status.get("running", False)
                error_logs = application_status.get(
                    "error_logs", "Could not get error logs"
                )
                node_tree.add(f"Name: {name}")
                node_tree.add(f"Running: {running}")
                node_tree.add(f"Error Logs:\n{error_logs}")
            elif node_type == "BroadbandSource":
                source = node.get("broadband_source", {})
                if "signal" in source and "electrode" in source["signal"]:
                    channels = source["signal"]["electrode"].get("channels", [])
                    electrode_ids = [
                        str(ch.get("electrode_id", "?")) for ch in channels
                    ]
                    node_tree.add(
                        f"Electrodes ({len(channels)}): {', '.join(electrode_ids)}"
                    )

        return tree


def visualize_peripherals(info_dict):
    tree = Tree("Peripherals")
    peripherals = info_dict.get("peripherals", [])
    if peripherals:
        for peripheral in peripherals:
            peripheral_tree = tree.add(
                f"{peripheral.get('name', 'Unknown')} ({peripheral.get('vendor', 'Unknown')})"
            )
            peripheral_tree.add(f"ID: {peripheral.get('peripheral_id', 'Unknown')}")
            peripheral_tree.add(f"Type: {peripheral.get('type', 'Unknown')}")
    else:
        tree.add("No peripherals found")
    return tree


class DeviceInfoDisplay:
    """A class for displaying device information."""

    def __init__(self):
        self.console = Console()

    def summary(self, device: Device):
        info = device.info()
        info_dict = MessageToDict(info, preserving_proto_field_name=True)

        status = info_dict.get("status", {})

        self.console.print(
            f"Name: [bold cyan]{info_dict.get('name', 'Unknown')}[/bold cyan]",
        )

        if status:
            state = status.get("state", "Unknown").replace("k", "")
            state = {
                "Running": "[green]Running[/green]",
                "Stopped": "[red]Stopped[/red]",
                "Unknown": "[yellow]Unknown[/yellow]",
            }.get(state, "[yellow]Unknown[/yellow]")
            self.console.print(f"Status: {state}")

        self.console.print(
            f"Serial: {info_dict.get('serial', 'Unknown')}",
            highlight=False,
        )
        self.console.print(
            f"Synapse Version: {info_dict.get('synapse_version', 'Unknown')}",
            highlight=False,
        )
        self.console.print(
            f"Firmware Version: {info_dict.get('firmware_version', 'Unknown')}",
            highlight=False,
        )

        if status:
            if "power" in status:
                battery = status["power"].get("battery_level_percent", "N/A")
                self.console.print(f"Battery: {battery}%", highlight=False)

            if "storage" in status:
                storage = status["storage"]
                total = float(storage.get("total_gb", 0))
                used = float(storage.get("used_gb", 0))
                used_percent = (used / total * 100) if total > 0 else 0
                self.console.print(
                    f"Storage: {used_percent:.1f}% used ({used:.1f}GB / {total:.1f}GB)",
                    highlight=False,
                )

            self.console.print(visualize_peripherals(info_dict))
            self.console.print(visualize_configuration(info_dict, status))
