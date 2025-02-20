#!/usr/bin/env python3

import sys
import json
import os
from datetime import datetime
import lxml.etree as ET

from ncclient import manager
# Updated imports here:
from ncclient.operations.rpc import RPCError, RPCTimeoutError, OperationError


def load_devices_from_json(json_file):
    """
    Reads the JSON file containing device information.
    Returns a list of device dictionaries.
    """
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("devices", [])
    except FileNotFoundError:
        print(f"Error: JSON file '{json_file}' not found.")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Failed to parse JSON from '{json_file}'. Check file format.")
        sys.exit(1)


def get_running_config(netconf_manager):
    """
    Retrieves the full running config in XML from a Junos device via ncclient.
    """
    response = netconf_manager.get_config(source='running')
    return str(response)


def save_config_to_file(hostname, config_str):
    """
    Saves the config string to <hostname>_<timestamp>.xml in the current directory.
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{hostname}_{timestamp}.xml"
    filepath = os.path.join(os.getcwd(), filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(config_str)
        print(f"[INFO] Saved config for '{hostname}' to {filepath}")
    except OSError as e:
        print(f"[ERROR] Failed to save file '{filepath}': {e}")


def push_config_ncclient(device_params, config_snippet):
    """
    Connects via ncclient, retrieves current config, backs it up, then loads
    the snippet into the candidate config, does a commit-check and commit.
    """
    host = device_params['host']
    print(f"[INFO] Connecting to {host}...")

    conn_params = {
        'host': host,
        'port': device_params.get('port', 830),
        'username': device_params.get('username'),
        'password': device_params.get('password'),
        'device_params': {'name': 'junos'},
        'timeout': 30
    }

    try:
        with manager.connect(**conn_params) as mgr:
            print(f"[INFO] Connected to {host}. Retrieving config...")
            running_config = get_running_config(mgr)
            save_config_to_file(host, running_config)

            # Lock candidate
            mgr.lock(target='candidate')
            print(f"[INFO] Candidate config locked on {host}.")

            # Load config snippet (merge by default)
            mgr.edit_config(target='candidate', config=config_snippet, default_operation='merge')
            print(f"[INFO] Loaded config snippet on {host}.")

            # Commit check (Junos-specific RPC)
            commit_check_rpc = """
            <commit-configuration>
                <check/>
            </commit-configuration>
            """
            mgr.dispatch(ET.fromstring(commit_check_rpc.strip()))
            print(f"[INFO] Commit check passed on {host}.")

            # Actual commit
            commit_rpc = "<commit-configuration/>"
            mgr.dispatch(ET.fromstring(commit_rpc.strip()))
            print(f"[INFO] Commit successful on {host}.")

            # Unlock
            mgr.unlock(target='candidate')
            print(f"[INFO] Candidate config unlocked on {host}.")

    except RPCError as rpc_err:
        print(f"[ERROR] RPC error on {host}: {rpc_err}")
        # Discard changes
        try:
            mgr.discard_changes()
            print("[INFO] Discarded uncommitted changes.")
        except Exception as disc_err:
            print(f"[ERROR] Discard changes failed: {disc_err}")

    except RPCTimeoutError as to_err:
        print(f"[ERROR] RPC timeout on {host}: {to_err}")
        # Discard changes
        try:
            mgr.discard_changes()
            print("[INFO] Discarded uncommitted changes.")
        except Exception as disc_err:
            print(f"[ERROR] Discard changes failed: {disc_err}")

    except OperationError as op_err:
        print(f"[ERROR] Operation error on {host}: {op_err}")
        # Discard changes
        try:
            mgr.discard_changes()
            print("[INFO] Discarded uncommitted changes.")
        except Exception as disc_err:
            print(f"[ERROR] Discard changes failed: {disc_err}")

    except Exception as e:
        print(f"[ERROR] Unexpected error on {host}: {e}")
        # Discard changes
        try:
            mgr.discard_changes()
            print("[INFO] Discarded uncommitted changes.")
        except Exception as disc_err:
            print(f"[ERROR] Discard changes failed: {disc_err}")


def main():
    """
    Usage: python script_ncclient.py devices.json config_snippet.xml
    """
    if len(sys.argv) < 3:
        print("Usage: python script_ncclient.py <devices.json> <config_snippet.xml>")
        sys.exit(1)

    json_file = sys.argv[1]
    xml_file = sys.argv[2]

    # Load device info
    devices = load_devices_from_json(json_file)
    if not devices:
        print("[WARNING] No devices found in JSON file.")
        sys.exit(0)

    # Read XML snippet
    try:
        with open(xml_file, 'r', encoding='utf-8') as f:
            config_snippet = f.read()
    except FileNotFoundError:
        print(f"[ERROR] XML file '{xml_file}' not found.")
        sys.exit(1)
    except OSError as e:
        print(f"[ERROR] Could not read XML file '{xml_file}': {e}")
        sys.exit(1)

    # Push config to each device
    for dev_params in devices:
        push_config_ncclient(dev_params, config_snippet)


if __name__ == '__main__':
    main()