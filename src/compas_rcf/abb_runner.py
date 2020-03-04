"""Fabrication runner for Rapid Clay Fabrication project for fullscale structure.

Run from command line using :code:`python -m compas_rcf.abb_rcf_runner`
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import json
import logging as log
import pathlib
import sys
import time
from datetime import datetime
from operator import attrgetter

from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Vector
from compas_fab.backends.ros import RosClient
from compas_rrc import AbbClient
from compas_rrc import PrintText
from compas_rrc import StartWatch
from compas_rrc import StopWatch
from compas_rrc import ReadWatch
from compas_rrc import MoveToFrame
from compas_rrc import SetWorkObject
from compas_rrc import SetTool


from compas_rcf import __version__
from compas_rcf.abb import connection_check
from compas_rcf.abb import docker_compose_paths
from compas_rcf.abb import post_procedure
from compas_rcf.abb import pre_procedure
from compas_rcf.abb import robot_ips
from compas_rcf.docker import compose_up
from compas_rcf.fabrication.conf import ZoneDataTemplate
from compas_rcf.fabrication.clay_obj import ClayBulletEncoder
from compas_rcf.fabrication.conf import FABRICATION_CONF as fab_conf
from compas_rcf.fabrication.conf import Path
from compas_rcf.fabrication.conf import interactive_conf_setup
from compas_rcf.utils import ui
from compas_rcf.abb.programs import get_offset_frame
from compas_rcf.abb.programs import grip_and_release
from compas_rcf.utils.json_ import load_bullets

if sys.version_info[0] < 2:
    raise Exception("This module requires Python 3")
else:
    import questionary

PREFIX = "t_A057_"
TOOLS = [PREFIX + "triple0", PREFIX + "triple1", PREFIX + "triple2"]


def triple_pick(client, picking_frames):
    """Send movement and IO instructions to pick up a clay bullet.

    Parameters
    ----------
    client : :class:`compas_rrc.AbbClient`
    picking_frame : compas.geometry.Frame
        Target frame to pick up bullet
    """
    watches = {}

    # start watch
    client.send(StartWatch())

    client.send(SetWorkObject(fab_conf["wobjs"]["picking_wobj_name"].get()))
    client.send(SetTool(TOOLS[1]))

    client.send(
        MoveToFrame(
            picking_frames[0],
            fab_conf["movement"]["speed_travel"].as_number(),
            fab_conf["movement"]["zone_travel"].get(ZoneDataTemplate()),
        )
    )

    client.send(StopWatch())

    watches.update({"travel": client.send(ReadWatch())})

    for j, frame in enumerate(picking_frames):
        client.send(StartWatch())

        # change work object before picking
        client.send(SetTool(TOOLS[j]))

        # pick bullet
        offset_picking = get_offset_frame(
            frame, fab_conf["movement"]["offset_distance"].get()
        )

        client.send(
            MoveToFrame(
                offset_picking,
                fab_conf["movement"]["speed_travel"].as_number(),
                fab_conf["movement"]["zone_travel"].get(ZoneDataTemplate()),
            )
        )

        client.send(
            MoveToFrame(
                frame,
                fab_conf["movement"]["speed_travel"].as_number(),
                fab_conf["movement"]["zone_travel"].get(ZoneDataTemplate()),
            )
        )

        grip_and_release(client, fab_conf["tool"]["grip_state"].get(int))

        client.send(
            MoveToFrame(
                offset_picking,
                fab_conf["movement"]["speed_picking"].as_number(),
                fab_conf["movement"]["zone_pick"].get(ZoneDataTemplate()),
            )
        )

        client.send(StopWatch())

        watches.update({"pick{}".format(j): client.send(ReadWatch())})

    return watches


def place_bullet_triple(client, bullets):
    """Send movement and IO instructions to place a clay bullet.

    Parameters
    ----------
    client : :class:`compas_rrc.AbbClient`
    picking_frame : compas.geometry.Frame
        Target frame to pick up bullet
    """
    watches = {}
    client.send(SetWorkObject(fab_conf["wobjs"]["placing_wobj_name"].as_str()))

    for n, bullet in enumerate(bullets):
        log.debug("Location frame: {}".format(bullet.location))

        # change work object before placing
        client.send(SetTool(TOOLS[n]))

        # add offset placing plane to pre and post frames

        top_bullet_frame = get_offset_frame(bullet.location, bullet.height)
        offset_placement = get_offset_frame(
            top_bullet_frame, fab_conf["movement"]["offset_distance"].as_number()
        )

        # Safe pos then vertical offset
        if n == 0:
            client.send(StartWatch())
            for frame in bullet.trajectory_to:
                client.send(
                    MoveToFrame(
                        frame,
                        fab_conf["movement"]["speed_travel"].as_number(),
                        fab_conf["movement"]["zone_travel"].get(ZoneDataTemplate()),
                    )
                )
            client.send(StopWatch())
            watches.update({"trajectory_to": client.send(ReadWatch())})

        client.send(StartWatch())

        client.send(
            MoveToFrame(
                offset_placement,
                fab_conf["movement"]["speed_travel"].as_number(),
                fab_conf["movement"]["zone_travel"].get(ZoneDataTemplate()),
            )
        )
        client.send(
            MoveToFrame(
                top_bullet_frame,
                fab_conf["movement"]["speed_placing"].as_number(),
                fab_conf["movement"]["zone_place"].get(ZoneDataTemplate()),
            )
        )

        grip_and_release(client, fab_conf["tool"]["release_state"].get(int))

        client.send(
            MoveToFrame(
                bullet.placement_frame,
                fab_conf["movement"]["speed_placing"].as_number(),
                fab_conf["movement"]["zone_place"].get(ZoneDataTemplate()),
            )
        )

        client.send(
            MoveToFrame(
                offset_placement,
                fab_conf["movement"]["speed_travel"].as_number(),
                fab_conf["movement"]["zone_travel"].get(ZoneDataTemplate()),
            )
        )

        client.send(StopWatch())
        watches.update({"place{}".format(n): client.send(ReadWatch())})

        # offset placement frame then safety frame
        if n == 2:
            client.send(StartWatch())
            for frame in bullet.trajectory_from:
                client.send(
                    MoveToFrame(
                        frame,
                        fab_conf["movement"]["speed_travel"].as_number(),
                        fab_conf["movement"]["zone_travel"].get(ZoneDataTemplate()),
                    )
                )
            client.send(StopWatch())
            watches.update({"trajectory_from": client.send(ReadWatch())})

    return watches


def pick_frame_from_grid(index, bullet_height):
    """Get next picking frame.

    Parameters
    ----------
    index : int
        Counter to iterate through picking positions.
    bullet_height : float
        Height of bullet to pick up.

    Returns
    -------
    list of `class`:compas.geometry.Frame
    """
    # If index is larger than amount on picking plate, start from zero again
    index *= 3
    index = index % (fab_conf["pick"]["xnum"].get() * fab_conf["pick"]["ynum"].get())

    picking_frames = []
    for k in range(3):

        xpos = (index + k) % fab_conf["pick"]["xnum"].get()
        ypos = (index + k) // fab_conf["pick"]["xnum"].get()

        x = (
            fab_conf["pick"]["origin_grid"]["x"].get()
            + xpos * fab_conf["pick"]["grid_spacing"].get()
        )
        y = (
            fab_conf["pick"]["origin_grid"]["y"].get()
            + ypos * fab_conf["pick"]["grid_spacing"].get()
        )
        z = bullet_height * fab_conf["pick"]["compression_height_factor"].get()

        frame = Frame(
            Point(x, y, z),
            Vector(*fab_conf["pick"]["xaxis"].get()),
            Vector(*fab_conf["pick"]["yaxis"].get()),
        )
        picking_frames.append(frame)
        # log.debug("Picking frame {:03d}: {}".format(index, frame))
    return picking_frames


def logging_setup():
    timestamp_file = datetime.now().strftime("%Y%m%d-%H.%M_rcf_abb.log")
    log_file = fab_conf["paths"]["log_dir"].get(Path()) / timestamp_file

    handlers = []

    if not fab_conf["skip_logfile"].get():
        handlers.append(log.FileHandler(log_file, mode="a"))
    if fab_conf["quiet"].get() is not True:
        handlers.append(log.StreamHandler(sys.stdout))

    log.basicConfig(
        level=log.DEBUG if fab_conf["debug"].get() else log.INFO,
        format="%(asctime)s:%(levelname)s:%(funcName)s:%(message)s",
        handlers=handlers,
    )


def setup_fab_data(clay_bullets):
    """Check for placed bullets in JSON.

    Parameters
    ----------
    clay_bullets : list of :class:`compas_rcf.fabrication.clay_objs.ClayBullet`
        Original list of ClayBullets.

    Returns
    -------
    list of :class:`compas_rcf.fabrication.clay_objs.ClayBullet`
        Curated list of ClayBullets
    """
    maybe_placed = [bullet for bullet in clay_bullets if bullet.placed is not None]

    if len(maybe_placed) < 1:
        return clay_bullets

    last_placed = max(maybe_placed, key=attrgetter("bullet_id"))
    last_placed_index = clay_bullets.index(last_placed)

    log.info(
        "Last bullet placed was {:03}/{:03} with id {}.".format(
            last_placed_index, len(clay_bullets), last_placed.bullet_id
        )
    )

    skip_options = questionary.select(
        "Some or all bullet seems to have been placed already.",
        [
            "Skip all bullet marked as placed in JSON file.",
            "Place all anyways.",
            questionary.Separator(),
            "Place some of the bullets.",
        ],
    ).ask()

    if skip_options == "Skip all bullet marked as placed in JSON file.":
        to_place = [bullet for bullet in clay_bullets if bullet not in maybe_placed]
    if skip_options == "Place all anyways.":
        to_place = clay_bullets[:]
    if skip_options == "Place some of the bullets.":
        skip_method = questionary.select(
            "Select method:",
            ["Place last N bullets again.", "Pick bullets to place again."],
        ).ask()
        if skip_method == "Place last N bullets again.":
            n_place_again = questionary.text(
                "Number of bullets from last to place again?",
                "1",
                lambda val: val.isdigit() and -1 < int(val) < last_placed_index,
            ).ask()
            to_place = clay_bullets[last_placed_index - int(n_place_again) + 1 :]
            log.info(
                "Placing last {} bullets again. First bullet will be id {}.".format(
                    n_place_again, to_place[0].bullet_id,
                )
            )
        else:
            to_place_selection = questionary.checkbox(
                "Select bullets:",
                [
                    "{:03} (id {}), marked placed: {}".format(
                        i, bullet.bullet_id, bullet.placed is not None
                    )
                    for i, bullet in enumerate(clay_bullets)
                ],
            ).ask()
            indices = [int(bullet.split()[0]) for bullet in to_place_selection]
            to_place = [clay_bullets[i] for i in indices]

    return to_place


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


################################################################################
# Script runner                                                                #
################################################################################
def abb_run():
    """Fabrication runner, sets conf, reads json input and runs fabrication process."""

    # CONF setup
    interactive_conf_setup()

    ############################################################################
    # Docker setup                                                            #
    ############################################################################
    compose_up(docker_compose_paths["base"], remove_orphans=False)
    log.debug("Compose up base")
    ip = robot_ips[fab_conf["target"].as_str()]
    compose_up(docker_compose_paths["abb_driver"], ROBOT_IP=ip)
    log.debug("Compose up abb_driver")

    ############################################################################
    # Load fabrication data                                                    #
    ############################################################################
    json_path = pathlib.Path(ui.open_file_dialog(fab_conf["paths"]["json_dir"].get()))
    clay_bullets = load_bullets(json_path)
    log.info("Fabrication data read from: {}".format(json_path))
    log.info("{} items in clay_bullets.".format(len(clay_bullets)))

    ############################################################################
    # Create Ros Client                                                        #
    ############################################################################
    ros = RosClient()

    ############################################################################
    # Create ABB Client                                                        #
    ############################################################################
    abb = AbbClient(ros)
    abb.run()
    log.debug("Connected to ROS")

    connection_check(abb)

    ############################################################################
    # setup in_progress JSON                                                   #
    ############################################################################
    json_progress_identifier = "IN_PROGRESS-"

    if json_path.name.startswith(json_progress_identifier):
        in_progress_json = json_path
    else:
        in_progress_json = json_path.with_name(
            json_progress_identifier + json_path.name
        )
    to_place = setup_fab_data(clay_bullets)

    if not questionary.confirm("Ready to start program?").ask():
        log.critical("Program exited because user didn't confirm start.")
        print("Exiting.")
        sys.exit()

    # Set speed, accel, tool, wobj and move to start pos
    pre_procedure(abb)

    for bullet in to_place:
        bullet.placed = None
        bullet.cycle_time = None

    ############################################################################
    # Fabrication loop                                                         #
    ############################################################################

    chunks_to_place = list(chunks(to_place, 3))
    times = []

    for i, chunk in enumerate(chunks_to_place):
        if len(chunk) != 3:
            break
        current_bullet_desc = "Bullet {:03}/{:03} with id {}.".format(
            i, len(to_place) - 1, bullet.bullet_id
        )

        abb.send(PrintText(current_bullet_desc))
        log.info(current_bullet_desc)

        pick_frames = pick_frame_from_grid(i * 3, 150)

        # Pick bullet
        pick_future = triple_pick(abb, pick_frames)

        pick_cycle = {}
        for key in pick_future:
            pick_cycle.update({key: pick_future[key].result()})

        # Place bullet
        place_futures = place_bullet_triple(abb, chunk)

        place_cycle = {}
        for key in place_futures:
            place_cycle.update({key: place_futures[key].result()})

        times.append({**pick_cycle, **place_cycle})
        log.debug("Cycle time was {}".format(bullet.cycle_time))
        for bullet in chunk:
            bullet.placed = time.time()
        log.debug("Time placed was {}".format(bullet.placed))

        with in_progress_json.open(mode="w") as fp:
            json.dump(times, fp)

    ############################################################################
    # Shutdown procedure                                                       #
    ############################################################################

    if len([bullet for bullet in clay_bullets if bullet.placed is None]) == 0:
        done_file_name = json_path.name.replace(json_progress_identifier, "")
        done_json = (
            fab_conf["paths"]["json_dir"].get(Path()) / "00_done" / done_file_name
        )

        in_progress_json.rename(done_json)

        with done_json.open(mode="w") as fp:
            json.dump(clay_bullets, fp, cls=ClayBulletEncoder)

        log.debug("Saved placed bullets to 00_Done.")
    else:
        log.debug(
            "Bullets without placed timestamp still present, keeping {}".format(
                in_progress_json.name
            )
        )

    log.info("Finished program with {} bullets.".format(len(to_place)))

    post_procedure(abb)


if __name__ == "__main__":
    """Entry point and argument handling."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-t",
        "--target",
        choices=["real", "virtual"],
        help="Set fabrication runner target.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Don't print logging messages to console.",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Log DEBUG level messages."
    )
    parser.add_argument(
        "--skip-logfile", action="store_true", help="Don't send log messages to file.",
    )

    args = parser.parse_args()

    fab_conf.set_args(args)

    logging_setup()

    log.info("compas_rcf version: {}".format(__version__))
    log.debug("argparse input: {}".format(args))
    log.debug("config after set_args: {}".format(fab_conf))

    abb_run()
