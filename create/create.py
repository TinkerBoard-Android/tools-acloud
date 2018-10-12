#!/usr/bin/env python
#
# Copyright 2018 - The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
r"""Create entry point.

Create will handle all the logic related to creating a local/remote instance
an Android Virtual Device and the logic related to prepping the local/remote
image artifacts.
"""

from __future__ import print_function

from distutils.spawn import find_executable
import os
import subprocess
import sys

from acloud import errors
from acloud.create import avd_spec
from acloud.create import local_image_local_instance
from acloud.create import local_image_remote_instance
from acloud.create import remote_image_remote_instance
from acloud.create import remote_image_local_instance
from acloud.internal import constants
from acloud.internal.lib import utils
from acloud.setup import setup
from acloud.setup import gcp_setup_runner
from acloud.setup import host_setup_runner

_MAKE_CMD = "build/soong/soong_ui.bash"
_MAKE_ARG = "--make-mode"


def GetAvdCreatorClass(instance_type, image_source):
    """Return the creator class for the specified spec.

    Based on the image source and the instance type, return the proper
    creator class.

    Args:
        instance_type: String, the AVD instance type (local or remote).
        image_source: String, the source of the image (local or remote).

    Returns:
        An AVD creator class (e.g. LocalImageRemoteInstance).
    """
    if (instance_type == constants.INSTANCE_TYPE_REMOTE and
            image_source == constants.IMAGE_SRC_LOCAL):
        return local_image_remote_instance.LocalImageRemoteInstance
    if (instance_type == constants.INSTANCE_TYPE_LOCAL and
            image_source == constants.IMAGE_SRC_LOCAL):
        return local_image_local_instance.LocalImageLocalInstance
    if (instance_type == constants.INSTANCE_TYPE_REMOTE and
            image_source == constants.IMAGE_SRC_REMOTE):
        return remote_image_remote_instance.RemoteImageRemoteInstance
    if (instance_type == constants.INSTANCE_TYPE_LOCAL and
            image_source == constants.IMAGE_SRC_REMOTE):
        return remote_image_local_instance.RemoteImageLocalInstance

    raise errors.UnsupportedInstanceImageType(
        "unsupported creation of instance type: %s, image source: %s" %
        (instance_type, image_source))


def _CheckForAutoconnect(args):
    """Check that we have all prerequisites for autoconnect.

    Autoconnect requires adb and ssh, we'll just check for adb for now and
    assume ssh is everywhere. If adb isn't around, ask the user if they want us
    to build it, if not we'll disable autoconnect.

    Args:
        args: Namespace object from argparse.parse_args.
    """
    if not args.autoconnect or find_executable(constants.ADB_BIN):
        return

    disable_autoconnect = False
    answer = utils.InteractWithQuestion(
        "adb is required for autoconnect, without it autoconnect will be "
        "disabled, would you like acloud to build it[y]? ")
    if answer in constants.USER_ANSWER_YES:
        utils.PrintColorString("Building adb ... ", end="")
        android_build_top = os.environ.get(
            constants.ENV_ANDROID_BUILD_TOP)
        if not android_build_top:
            utils.PrintColorString("Fail! (Not in a lunch'd env)",
                                   utils.TextColors.FAIL)
            disable_autoconnect = True
        else:
            make_cmd = os.path.join(android_build_top, _MAKE_CMD)
            build_adb_cmd = [make_cmd, _MAKE_ARG, "adb"]
            try:
                with open(os.devnull, "w") as dev_null:
                    subprocess.check_call(build_adb_cmd, stderr=dev_null,
                                          stdout=dev_null)
                    utils.PrintColorString("OK!", utils.TextColors.OKGREEN)
            except subprocess.CalledProcessError:
                utils.PrintColorString("Fail! (build failed)",
                                       utils.TextColors.FAIL)
                disable_autoconnect = True
    else:
        disable_autoconnect = True

    if disable_autoconnect:
        utils.PrintColorString("Disabling autoconnect",
                               utils.TextColors.WARNING)
        args.autoconnect = False


def _CheckForSetup(args):
    """Check that host is setup to run the create commands.

    We'll check we have the necessary bits setup to do what the user wants, and
    if not, tell them what they need to do before running create again.

    Args:
        args: Namespace object from argparse.parse_args.
    """
    run_setup = False
    # Need to set all these so if we need to run setup, it won't barf on us
    # because of some missing fields.
    args.gcp_init = False
    args.host = False
    args.force = False
    # Remote image/instance requires the GCP config setup.
    if not args.local_instance or args.local_image == "":
        gcp_setup = gcp_setup_runner.GcpTaskRunner(args.config_file)
        if gcp_setup.ShouldRun():
            args.gcp_init = True
            run_setup = True

    # Local instance requires host to be setup.
    if args.local_instance:
        host_pkg_setup = host_setup_runner.AvdPkgInstaller()
        host_env_setup = host_setup_runner.CuttlefishHostSetup()
        if host_pkg_setup.ShouldRun() or host_env_setup.ShouldRun():
            args.host = True
            run_setup = True

    if run_setup:
        answer = utils.InteractWithQuestion("Missing necessary acloud setup, "
                                            "would you like to run setup[y]?")
        if answer in constants.USER_ANSWER_YES:
            setup.Run(args)
        else:
            print("Please run '#acloud setup' so we can get your host setup")
            sys.exit()


def PreRunCheck(args):
    """Do some pre-run checks to ensure a smooth create experience.

    Args:
        args: Namespace object from argparse.parse_args.
    """
    _CheckForSetup(args)
    _CheckForAutoconnect(args)


def Run(args):
    """Run create.

    Args:
        args: Namespace object from argparse.parse_args.
    """
    PreRunCheck(args)
    spec = avd_spec.AVDSpec(args)
    avd_creator_class = GetAvdCreatorClass(spec.instance_type,
                                           spec.image_source)
    avd_creator = avd_creator_class()
    report = avd_creator.Create(spec)
    if report and args.report_file:
        report.Dump(args.report_file)
