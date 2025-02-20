#!/usr/bin/env python3
"""
Script to:
1. Read multiple device login info from a JSON file.
2. Connect to each device over NETCONF (PyEZ).
3. Retrieve current config in XML format and save to <hostname>_<timestamp>.xml.
4. Push new configuration (snippet) to each device and commit changes atomically.
"""

import os
import sys
import json
from datetime import datetime
from lxml import etree  # For converting XML Element to string

from jnpr.junos import Device
from jnpr.junos.utils.config import Config
from jnpr.junos.exception import (
    ConnectRefusedError,
    RpcError,
    ConnectError,
    CommitError
)


def load_devices_from_json(json_file):
    """
    Reads the JSON file containing device information.
    Returns a list of device dictionaries.
    """
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
        # Expecting: {"devices": [ {...}, {...} ]}
        return data.get("devices", [])
    except FileNotFoundError:
        print(f"Error: JSON file '{json_file}' not found.")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Failed to parse JSON from '{json_file}'. Check file format.")
        sys.exit(1)


def retrieve_config_xml(device_params):
    """
    Connects to a Junos device using PyEZ, retrieves the current config in XML.
    Returns a tuple: (hostname, xml_config_string).
    """
    dev_params = {
        'host': device_params['host'],
        'user': device_params.get('user', 'root'),
        'passwd': device_params.get('passwd', ''),
        'port': device_params.get('port', 830),
        'gather_facts': True
    }

    try:
        with Device(**dev_params) as dev:
            device_hostname = dev.facts.get('hostname') or dev.host
            # Retrieve config in XML format
            config_xml = dev.rpc.get_config(options={'format': 'xml'})
            # Convert from an lxml Element to a string
            config_str = etree.tostring(config_xml, encoding='unicode')
            return device_hostname, config_str

    except ConnectRefusedError:
        print(f"Error: NETCONF connection to {device_params['host']} was refused.")
    except ConnectError as ce:
        print(f"Error: Failed to connect to {device_params['host']}. Reason: {ce}")
    except RpcError as re:
        print(f"Error: RPC error while retrieving config from {device_params['host']}: {re}")

    return None, None


def save_config_to_file(hostname, config_str):
    """
    Saves the config string to a file named <hostname>_<timestamp>.xml
    in the current working directory.
    """
    if not hostname or not config_str:
        return

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{hostname}_{timestamp}.xml"
    file_path = os.path.join(os.getcwd(), filename)

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(config_str)
        print(f"[INFO] Configuration for '{hostname}' saved to: {file_path}")
    except OSError as e:
        print(f"[ERROR] Saving file '{file_path}': {e}")


def push_config_to_device(device_params, config_snippet):
    """
    Connects to the device, locks config, loads 'config_snippet' (XML),
    commits changes, handles errors with rollback, then unlocks.
    """
    dev_params = {
        'host': device_params['host'],
        'user': device_params.get('user', 'root'),
        'passwd': device_params.get('passwd', ''),
        'port': device_params.get('port', 830),
        'gather_facts': False  # We don't need facts here, so we skip them
    }

    try:
        with Device(**dev_params) as dev:
            cfg = Config(dev)
            # Lock config
            cfg.lock()
            print(f"[INFO] Locked configuration on {dev.host}.")

            # Load snippet in XML format
            cfg.load(config_snippet, format='xml', merge=True)
            print(f"[INFO] Loaded config snippet on {dev.host}.")

            # Commit check
            cfg.commit_check()
            print(f"[INFO] Commit check successful on {dev.host}.")

            # Commit
            cfg.commit()
            print(f"[INFO] Configuration committed on {dev.host}.")

            # Unlock config
            cfg.unlock()
            print(f"[INFO] Unlocked configuration on {dev.host}.")

    except RpcError as rpc_err:
        print(f"[ERROR] RPC error on {dev_params['host']}: {rpc_err}")
        # Attempt a rollback
        try:
            cfg.rollback()
            print("[INFO] Rollback performed.")
        except Exception as rb_err:
            print(f"[ERROR] Rollback failed: {rb_err}")

    except CommitError as commit_err:
        print(f"[ERROR] Commit failed on {dev_params['host']}: {commit_err}")
        # Attempt a rollback
        try:
            cfg.rollback()
            print("[INFO] Rollback performed.")
        except Exception as rb_err:
            print(f"[ERROR] Rollback failed: {rb_err}")

    except Exception as e:
        print(f"[ERROR] Unexpected error on {dev_params['host']}: {e}")
        # Attempt a rollback
        try:
            cfg.rollback()
            print("[INFO] Rollback performed.")
        except Exception as rb_err:
            print(f"[ERROR] Rollback failed: {rb_err}")


def main():
    """
    Main function:
    - Read devices from JSON file passed as argument.
    - For each device, retrieve XML config and save locally.
    - Then push a sample VLAN config snippet to each device.
    """
    if len(sys.argv) < 2:
        print("Usage: python script.py <devices.json>")
        sys.exit(1)

    json_file = sys.argv[1]
    devices = load_devices_from_json(json_file)

    if not devices:
        print("[WARNING] No devices found in the JSON file.")
        sys.exit(0)

    # This is our sample snippet to push (XML format).
    # Example: Creating VLAN 20 with a description.
    CONFIG_SNIPPET = """
<configuration>
    <vlans>
        <vlan>
            <name>VLAN20</name>
            <vlan-id>20</vlan-id>
            <description>Created via PyEZ</description>
        </vlan>
    </vlans>
</configuration>
"""

    for dev_params in devices:
        # 1. Retrieve current config
        hostname, config_xml_str = retrieve_config_xml(dev_params)
        if hostname and config_xml_str:
            save_config_to_file(hostname, config_xml_str)

        # 2. Push the new config snippet
        push_config_to_device(dev_params, CONFIG_SNIPPET)


if __name__ == '__main__':
    main()
