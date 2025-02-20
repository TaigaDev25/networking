#!/usr/bin/env python3
"""
Script to:
1. Read multiple device login info from a JSON file.
2. Read configuration snippet to push from an XML file.
3. Connect to each device over NETCONF (PyEZ).
4. Retrieve current config in XML format and save to <hostname>_<timestamp>.xml.
5. Push the XML snippet to each device and commit changes atomically.
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
        'gather_facts': True  # so we can get dev.facts['hostname']
    }

    try:
        with Device(**dev_params) as dev:
            # Use either the discovered hostname (if gather_facts is True)
            # or the one in device_params
            device_hostname = dev.facts.get('hostname') or device_params['host']

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
        'gather_facts': False
    }

    log_host = device_params['host']  # For logging

    try:
        with Device(**dev_params) as dev:
            cfg = Config(dev)
            # Lock config
            cfg.lock()
            print(f"[INFO] Locked configuration on {log_host}.")

            # Load snippet in XML format
            cfg.load(config_snippet, format='xml', merge=True)
            print(f"[INFO] Loaded config snippet on {log_host}.")

            # Commit check
            cfg.commit_check()
            print(f"[INFO] Commit check successful on {log_host}.")

            # Commit
            cfg.commit()
            print(f"[INFO] Configuration committed on {log_host}.")

            # Unlock config
            cfg.unlock()
            print(f"[INFO] Unlocked configuration on {log_host}.")

    except RpcError as rpc_err:
        print(f"[ERROR] RPC error on {log_host}: {rpc_err}")
        # Attempt a rollback
        try:
            cfg.rollback()
            print("[INFO] Rollback performed.")
        except Exception as rb_err:
            print(f"[ERROR] Rollback failed: {rb_err}")

    except CommitError as commit_err:
        print(f"[ERROR] Commit failed on {log_host}: {commit_err}")
        # Attempt a rollback
        try:
            cfg.rollback()
            print("[INFO] Rollback performed.")
        except Exception as rb_err:
            print(f"[ERROR] Rollback failed: {rb_err}")

    except Exception as e:
        print(f"[ERROR] Unexpected error on {log_host}: {e}")
        # Attempt a rollback
        try:
            cfg.rollback()
            print("[INFO] Rollback performed.")
        except Exception as rb_err:
            print(f"[ERROR] Rollback failed: {rb_err}")


def main():
    """
    Main function:
    - Read devices from JSON file (first argument).
    - Read config snippet from an XML file (second argument).
    - For each device:
        - Retrieve XML config and save locally.
        - Push the snippet from the XML file and commit.
    """
    if len(sys.argv) < 3:
        print("Usage: python script.py <devices.json> <config_snippet.xml>")
        sys.exit(1)

    json_file = sys.argv[1]
    xml_snippet_file = sys.argv[2]

    # 1. Load device list from JSON
    devices = load_devices_from_json(json_file)

    if not devices:
        print("[WARNING] No devices found in the JSON file.")
        sys.exit(0)

    # 2. Read XML snippet to push
    try:
        with open(xml_snippet_file, 'r', encoding='utf-8') as f:
            config_snippet = f.read()
    except FileNotFoundError:
        print(f"[ERROR] XML file '{xml_snippet_file}' not found.")
        sys.exit(1)
    except OSError as e:
        print(f"[ERROR] Could not read XML file '{xml_snippet_file}': {e}")
        sys.exit(1)

    # 3. For each device, retrieve config -> save -> push snippet
    for dev_params in devices:
        hostname, config_xml_str = retrieve_config_xml(dev_params)
        if hostname and config_xml_str:
            save_config_to_file(hostname, config_xml_str)

        push_config_to_device(dev_params, config_snippet)


if __name__ == '__main__':
    main()
