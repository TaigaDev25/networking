#!/usr/bin/env python3
"""
Script to:
1. Read multiple device login info from a JSON file.
2. Connect to each device over NETCONF using PyEZ.
3. Retrieve current config in XML format.
4. Save the config to a file <hostname>_<timestamp>.xml.
"""

import os
import sys
import json
from datetime import datetime
from lxml import etree  # for converting XML Element to string

from jnpr.junos import Device
from jnpr.junos.exception import ConnectRefusedError, RpcError, ConnectError


def load_devices_from_json(json_file):
    """
    Reads the JSON file containing device information.
    Returns a list of device dictionaries.
    """
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
        # Expecting data in the form: {"devices": [ {...}, {...} ]}
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
    # Ensure gather_facts=True if you want 'dev.hostname' (or dev.facts['hostname'])
    dev_params = {
        'host': device_params['host'],
        'user': device_params.get('user', 'root'),
        'passwd': device_params.get('passwd', ''),
        'port': device_params.get('port', 830),
        'gather_facts': True  # to allow dev.hostname to be populated
    }

    try:
        with Device(**dev_params) as dev:
            # If dev.facts are gathered, we can use dev.hostname or dev.facts['hostname']
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

    # If we hit an error, return (None, None)
    return None, None


def save_config_to_file(hostname, config_str):
    """
    Saves the config string to a file named <hostname>_<timestamp>.xml
    in the current working directory.
    """
    if hostname is None or not config_str:
        return

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{hostname}_{timestamp}.xml"

    # Save in the same directory as the script (or use current working directory)
    file_path = os.path.join(os.getcwd(), filename)

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(config_str)
        print(f"Configuration for '{hostname}' saved to: {file_path}")
    except OSError as e:
        print(f"Error saving file '{file_path}': {e}")


def main():
    """
    Main function:
    - Reads devices from JSON file passed as argument.
    - For each device, retrieves the XML config and saves it.
    """
    if len(sys.argv) < 2:
        print("Usage: python script.py <devices.json>")
        sys.exit(1)

    json_file = sys.argv[1]
    devices = load_devices_from_json(json_file)

    if not devices:
        print("No devices found in the JSON file.")
        sys.exit(0)

    for dev_params in devices:
        hostname, config_xml_str = retrieve_config_xml(dev_params)
        if hostname and config_xml_str:
            save_config_to_file(hostname, config_xml_str)


if __name__ == '__main__':
    main()