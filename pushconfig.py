#!/usr/bin/env python3
"""
Script to retrieve existing Junos configuration, add a new VLAN (or routing policy),
and commit changes atomically with rollback on failure.
"""

import sys
from jnpr.junos import Device
from jnpr.junos.utils.config import Config
from jnpr.junos.exception import RpcError, ConnectRefusedError, CommitError


# ------------------------------------------------------------------------------
# Step 1: Define connection details
# ------------------------------------------------------------------------------
JUNOS_DEVICE = {
    'host': '192.168.56.10',
    'user': 'lab',
    'passwd': 'lab123',  # In a real environment, consider more secure methods (e.g., SSH key, vault, etc.)
    'port': 830,
    'gather_facts': False  # Speeds up connection; set True if you want device facts
}

# ------------------------------------------------------------------------------
# Step 2: Establish NETCONF session to the device
# ------------------------------------------------------------------------------
try:
    dev = Device(**JUNOS_DEVICE)
    dev.open()
    print(f"Successfully connected to {dev.hostname or dev.host}")
except ConnectRefusedError as e:
    print("NETCONF connection refused. Ensure NETCONF is enabled on the device.")
    sys.exit(1)
except Exception as e:
    print(f"Error connecting to device: {e}")
    sys.exit(1)


# ------------------------------------------------------------------------------
# Step 3: Retrieve existing configuration
#        Example: get the VLAN or BGP config from the device
# ------------------------------------------------------------------------------
try:
    # We can use device RPC calls directly. For example, to get the entire config:
    full_config_xml = dev.rpc.get_config(options={'format': 'xml'})
    
    # Or if you want only certain sections (e.g., VLAN config), you can use filters:
    # filter_xml = """
    #     <configuration>
    #         <vlans/>
    #     </configuration>
    # """
    # vlan_config_xml = dev.rpc.get_config(filter_xml, options={'format': 'xml'})
    
    print("Current configuration retrieved successfully.")
    # Debug: print(full_config_xml)
except RpcError as e:
    print(f"Failed to retrieve configuration via NETCONF: {e}")
    dev.close()
    sys.exit(1)


# ------------------------------------------------------------------------------
# Step 4: Build the new configuration snippet
#        Example snippet for VLAN 20 (you could add IRB interface, BGP policy, etc.)
# ------------------------------------------------------------------------------
# For demonstration, we will add VLAN 20 with a description. 
# In a more advanced example, you could add bridging, IRB interfaces, etc.

new_vlan_config = """
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

# Optionally, you could create a BGP policy snippet, for example:
# new_bgp_policy = """
# <configuration>
#     <policy-options>
#         <policy-statement>
#             <name>NEW-POLICY</name>
#             <term>
#                 <name>1</name>
#                 <from>
#                     <protocol>bgp</protocol>
#                 </from>
#                 <then>
#                     <accept/>
#                 </then>
#             </term>
#         </policy-statement>
#     </policy-options>
# </configuration>
# """


# ------------------------------------------------------------------------------
# Step 5: Load and commit the new configuration atomically
# ------------------------------------------------------------------------------
cu = Config(dev)

try:
    # 5.1: Lock the configuration (prevent others from editing)
    cu.lock()

    # 5.2: Load the config snippet
    cu.load(new_vlan_config, format='xml')
    # If you have more config to add, you could do multiple loads
    # cu.load(new_bgp_policy, format='xml', merge=True)

    # 5.3: Validate changes (commit check)
    cu.commit_check()

    # 5.4: Commit changes
    cu.commit()
    print("Configuration committed successfully!")

except RpcError as err:
    print(f"NETCONF RPC error during commit process: {err}")
    # Attempt rollback
    try:
        cu.rollback()
        print("Rolled back configuration due to error.")
    except Exception as re:
        print(f"Failed to rollback: {re}")

except CommitError as cerr:
    print(f"Commit error: {cerr}")
    # Attempt rollback
    try:
        cu.rollback()
        print("Rolled back configuration due to commit error.")
    except Exception as re:
        print(f"Failed to rollback: {re}")

except Exception as e:
    print(f"Unexpected error: {e}")
    # Attempt rollback
    try:
        cu.rollback()
        print("Rolled back configuration due to an unexpected error.")
    except Exception as re:
        print(f"Failed to rollback: {re}")

finally:
    # 5.5: Unlock config and close the connection
    try:
        cu.unlock()
    except Exception as e:
        print(f"Error unlocking configuration: {e}")

    dev.close()
    print("NETCONF session closed.")
