#!/usr/bin/env python3

import sys
import json
import os
from datetime import datetime
import lxml.etree as ET

from ncclient import manager
from ncclient.operations.errors import RPCError, TimeoutExpiredError, OperationError


def load_devices_from_json(json_file):
    """
    Reads the JSON file containing device information.
    Returns a list of device dictionaries.
    Expected format: {"devices": [{"host":"...", "username":"...", "password":"...", "port":830}, ...]}
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
    Retrieves the full running config in XML format from a Junos device
    via ncclient. Returns the config string.
    """
    # "get_config" is a standard NETCONF operation: we specify source='running'.
    response = netconf_manager.get_config(source='running')
    # response is an XML object -> convert to string
    return str(response)


def save_config_to_file(hostname, config_str):
    """
    Saves the config string to a file named <hostname>_<timestamp>.xml
    in the current working directory.
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{hostname}_{timestamp}.xml"
    file_path = os.path.join(os.getcwd(), filename)

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(config_str)
        print(f"[INFO] Configuration for '{hostname}' saved to: {file_path}")
    except OSError as e:
        print(f"[ERROR] Failed to save file '{file_path}': {e}")


def lock_candidate_config(mgr):
    """
    Locks the candidate configuration on a Junos device.
    Equivalent to "configure private" or "edit exclusive" in CLI terms.
    """
    # ncclient provides "lock" operation
    mgr.lock(target='candidate')


def unlock_candidate_config(mgr):
    """
    Unlocks the candidate configuration on a Junos device.
    """
    mgr.unlock(target='candidate')


def discard_changes(mgr):
    """
    Issues a discard-changes (standard NETCONF) to revert any uncommitted changes.
    """
    mgr.discard_changes()


def commit_check(mgr):
    """
    Perform a Juniper "commit check" by calling <commit-configuration> with <check/>.
    We can also do a standard NETCONF <validate> on candidate, but this is more
    direct for Junos.
    """
    commit_check_rpc = """
    <commit-configuration>
        <check/>
    </commit-configuration>
    """
    rpc_element = ET.fromstring(commit_check_rpc.strip())
    mgr.dispatch(rpc_element)


def commit_config(mgr):
    """
    Perform an actual Juniper commit by calling <commit-configuration>.
    """
    commit_rpc = """
    <commit-configuration/>
    """
    rpc_element = ET.fromstring(commit_rpc.strip())
    mgr.dispatch(rpc_element)


def push_config_ncclient(device_params, config_snippet):
    """
    Connects via ncclient, locks candidate, loads config snippet (merge),
    commit-check, commit, then unlock. On error, attempts to discard changes.
    """
    host = device_params['host']
    print(f"[INFO] Connecting to {host}...")

    # We default device_params keys to comply with manager.connect
    conn_params = {
        'host': host,
        'port': device_params.get('port', 830),
        'username': device_params.get('username'),
        'password': device_params.get('password'),
        'device_params': {'name': 'junos'},  # Tells ncclient it's a Junos device
        'timeout': 30
    }

    try:
        with manager.connect(**conn_params) as mgr:
            print(f"[INFO] Connected to {host}. Retrieving config...")

            # 1. Backup the current running config
            running_config = get_running_config(mgr)
            save_config_to_file(host, running_config)

            # 2. Lock candidate
            lock_candidate_config(mgr)
            print(f"[INFO] Candidate config locked on {host}.")

            # 3. Load config snippet with 'merge' (you can specify 'replace' if needed)
            #    config_snippet is the full <config>... snippet from the XML file
            mgr.edit_config(target='candidate', config=config_snippet, default_operation='merge')
            print(f"[INFO] Loaded config snippet on {host}.")

            # 4. Commit check
            commit_check(mgr)
            print(f"[INFO] Commit check passed on {host}.")

            # 5. Commit
            commit_config(mgr)
            print(f"[INFO] Commit successful on {host}.")

            # 6. Unlock candidate
            unlock_candidate_config(mgr)
            print(f"[INFO] Candidate config unlocked on {host}.")

    except RPCError as rpc_err:
        print(f"[ERROR] RPC Error on {host}: {rpc_err}")
        # Attempt discard-changes
        try:
            discard_changes(mgr)
            print("[INFO] Discarded uncommitted changes.")
        except Exception as disc_err:
            print(f"[ERROR] Discard changes failed: {disc_err}")

    except (TimeoutExpiredError, OperationError) as op_err:
        print(f"[ERROR] Operation error on {host}: {op_err}")
        # Attempt discard-changes
        try:
            discard_changes(mgr)
            print("[INFO] Discarded uncommitted changes.")
        except Exception as disc_err:
            print(f"[ERROR] Discard changes failed: {disc_err}")

    except Exception as e:
        print(f"[ERROR] Unexpected error on {host}: {e}")
        # Attempt discard-changes
        try:
            discard_changes(mgr)
            print("[INFO] Discarded uncommitted changes.")
        except Exception as disc_err:
            print(f"[ERROR] Discard changes failed: {disc_err}")


def main():
    """
    Usage: python script_ncclient.py <devices.json> <config_snippet.xml>
    - Reads device info from JSON
    - Reads config snippet from XML
    - Pushes snippet to each device using ncclient
    """
    if len(sys.argv) < 3:
        print("Usage: python script_ncclient.py <devices.json> <config_snippet.xml>")
        sys.exit(1)

    json_file = sys.argv[1]
    xml_file = sys.argv[2]

    # 1. Load devices from JSON
    devices = load_devices_from_json(json_file)
    if not devices:
        print("[WARNING] No devices found in JSON file.")
        sys.exit(0)

    # 2. Read the XML snippet from file
    try:
        with open(xml_file, 'r', encoding='utf-8') as f:
            config_snippet = f.read()
    except FileNotFoundError:
        print(f"[ERROR] XML file '{xml_file}' not found.")
        sys.exit(1)
    except OSError as e:
        print(f"[ERROR] Could not read XML file '{xml_file}': {e}")
        sys.exit(1)

    # 3. Push config to each device
    for dev_params in devices:
        push_config_ncclient(dev_params, config_snippet)


if __name__ == '__main__':
    main()