"""
This module manages communications and script execution
"""

import socket

import traceback
import struct
import math

# ------ Wraps communications


def concatenate_script(list_ur_commands):
    """
    Internal function that concatenates generated UR script into one large script file. Usually used to combine
    scripts generated by the GrasshopperPython components

    Args:
        list_ur_commands: A list of formatted UR Script strings

    Returns:
        ur_script: The concatenated script
    """

    ur_script = "\ndef clay_script():\n"
    # ur_script += '\tpopup("running MAS_clay_shooting_script")\n'

    combined_script = ""
    for ur_cmd in list_ur_commands:
        combined_script += ur_cmd

    # format combined script
    lines = combined_script.split("\n")
    for l in lines:
        ur_script += "\t" + l + "\n"

    ur_script += 'end\n'
    ur_script += '\nclay_script()\n'
    return ur_script


def stop_script():
    """
    Function that creates a UR script to stop both axis and ur robot

    Returns:
        ur_script: The stopping script
    """

    ur_script = "\ndef stop_script():\n"
    ur_script += '\tpopup("stopping script")\n'
    # Call axis to stop
    ur_script += "\tstop_ext_axis()\n"
    ur_script += "\twait_ext_axis()\n"
    # Call UR robot to stop
    ur_script += "\tstop program\n"
    ur_script += '\nend\n'
    ur_script += '\nstop_script()\n'
    return ur_script


def send_script(script_to_send, robot_id, offline_simulation):
    """
    Opens a socket to the Robot and sends a script

    Args:
        script_to_send: Script to send to socket
        robot_id: Integer. ID of robot

    """
    '''Function that opens a socket connection to the robot'''
    PORT = 30002
    HOST = get_ip_ur(robot_id, offline_simulation)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect((HOST, PORT))
    except:
        print("Cannot connect to ", HOST, PORT)

    s.settimeout(None)
    max_size = 2 << 18
    n = len(script_to_send)
    if n > max_size:
        raise Exception("Program too long")

    try:
        s.send(script_to_send)
    except:
        print("failed to send")
    s.close()


def get_ip_ur(ur_number, offline_simulation=False):
    """
    Function that gets the ip of the robot

    Args:
        ur_number: ID of robot (1,2 or 3)

    Returns:
        ip: string.
    """
    subnet = '192.168.10.'
    if not offline_simulation:
        ip = subnet + str(ur_number + 9)
    else:
        ip = 'localhost'
    print(ip)
    return ip


def _get_ip_axis(ur_number):
    """
    Internal function that gets the ip of the axis machine

    Args:
        ur_number: ID of robot (1,2 or 3)

    Returns:
        ip: string.
    """
    ip = 10 * ur_number
    return '192.168.10.%d' % ip


def create_ur_script(template, scripts, robot_id):
    """
    Function that creates final UR Script to be sent to the robot. It needs to be used with a template UR script file.
    The final script is used for a robot-axis setup.

    Args:
        template: A template UR script. This is usually fixed
        scripts: scripts to add to the body of the final script
        robot_id: ID of robot (1,2 or 3)

    Returns:
        ur_script: Formatted final scrip to send to robot
    """

    header = template.replace("<<<ip_axis>>>", _get_ip_axis(robot_id))
    body = concatenate_script(scripts)
    combined_script = header + body
    lines = combined_script.split("\n")

    ur_script = ""
    for l in lines:
        ur_script += "\t" + l + "\n"
    return ur_script


# ------ Real time


def listen_to_robot(robot_id, offline_simulation=False):
    PORT = 30003
    HOST = get_ip_ur(robot_id, offline_simulation)
    # Create dictionary to store data
    chunks = {}
    chunks["target_joints"] = []
    chunks["actual_joints"] = []
    chunks["forces"] = []
    chunks["pose"] = []
    chunks["time"] = [0]

    data = read(HOST, PORT)
    get_messages(data, chunks)
    return chunks


def read(HOST, PORT):
    """
    Method that opens a TCP socket to the robot, receives data from the robot server and then closes socket

    Returns:
        data: Data broadcast by the robot. In bytes
    """

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(.1)
    try:
        s.connect((HOST, PORT))
        print('connected')
    except:
        traceback.print_exc()
        print('Cannot connect to {}, {}'.format(HOST, PORT))
    # s.settimeout(None)
    data = s.recv(1024)
    s.close()
    return data


def get_messages(bytes, chunks_info):
    """
    Function parses data stream and selects the following information:
    1) q_target
    2) q_actual
    3) TCP force
    4) Tool Vector
    5) Time

    This data is formatted and the chunks dictionary is updated
    for more info see: http://wiki03.lynero.net/Technical/RealTimeClientInterface
    """

    # get messages
    q_target = bytes[12:60]
    q_actual = bytes[252:300]
    tcp_force = bytes[540:588]
    tool_vector = bytes[588:636]
    controller_time = bytes[740:748]

    # format type: int,
    fmt_double6 = "!dddddd"
    fmt_double1 = "!d"

    # Unpack selected data
    target_joints = struct.unpack(fmt_double6, q_target)
    chunks_info["target_joints"] = (math.degrees(j) for j in target_joints)
    actual_joints = struct.unpack(fmt_double6, q_actual)
    chunks_info["actual_joints"] = (math.degrees(j) for j in actual_joints)
    forces = struct.unpack(fmt_double6, tcp_force)
    chunks_info["forces"] = forces
    pose = struct.unpack(fmt_double6, tool_vector)
    chunks_info["pose"] = pose
    time = struct.unpack(fmt_double1, controller_time)
    chunks_info["time"] = time
