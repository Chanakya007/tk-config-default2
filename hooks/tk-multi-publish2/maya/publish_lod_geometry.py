# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import tempfile
import maya.cmds as cmds
import maya.mel as mel
import sgtk
from sgtk import TankError
from sgtk.util.filesystem import ensure_folder_exists

# A convenience wrapper on top of alembic's Python api
from dd.runtime import api
api.load("cask")
import cask

HookBaseClass = sgtk.get_hook_baseclass()


MAYA_GEOMETRY_ITEM_TYPE_SETTINGS = {
    "maya.geometry": {
        "publish_type": "Alembic Cache",
        "publish_name_template": None,
        "publish_path_template": None
    }
}


class MayaPublishGeometryPlugin(HookBaseClass):
    """
    Inherits from PublishFilesPlugin
    """
    @property
    def name(self):
        """
        One line display name describing the plugin
        """
        return "Publish Maya Geometry based on ModelPublish hierarchy"

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """

        return """
        <p>This plugin publishes session geometry for the current session. Any
        geometry LOD in the session will be exported to the path defined by this plugin's
        configured "Publish Template" setting. The plugin will fail to validate
        if the "AbcExport" plugin is not enabled or cannot be found.</p>
        """

    @property
    def settings_schema(self):
        """
        Dictionary defining the settings that this plugin expects to receive
        through the settings parameter in the accept, validate, publish and
        finalize methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default_value": "default_value",
                    "description": "One line description of the setting"
            }


        The type string should be one of the data types that toolkit accepts
        as part of its environment configuration.
        """
        schema = super(MayaPublishGeometryPlugin, self).settings_schema
        schema["Item Type Filters"]["default_value"] = ["maya.geometry"]
        schema["Item Type Settings"]["default_value"] = MAYA_GEOMETRY_ITEM_TYPE_SETTINGS
        schema["Export UVs"] = {
            "type": "bool",
            "description": "Specifies whether to export the UVs with the alembic",
            "allows_empty": True,
            "default_value": True
        }
        schema["Export WorldSpace"] = {
            "type": "bool",
            "description": "Specifies whether to export the alembic in worldspace",
            "allows_empty": True,
            "default_value": False
        }
        schema["Strip Namespace"] = {
            "type": "bool",
            "description": "Specifies whether to strip the namespace while exporting the alembic",
            "allows_empty": True,
            "default_value": False
        }
        return schema

    def _rename_abc_top_group(self, publish_path_temp, publish_path, rename_to):
        """
        This function renames the "top" group of the alembic heirarchy.

        :param string publish_path: Path of the alembic file to be modified.
        :param string rename_to: The new name that you would want to assign to the top group.
        """
        if not os.path.exists(publish_path_temp):
            self.logger.error("Invalid Alembic path : {0}. Not renaming the top group.".format(
                publish_path_temp))
            return

        # Loading the alembic archive
        abc_archive = cask.Archive(publish_path_temp)

        try:
            abc_archive.top.children.values()[0].name = rename_to
            abc_archive.write_to_file(publish_path, asOgawa=True)
        except Exception as err:
            import traceback
            self.logger.error(
                "Unhandled exceptions encountered.",
                extra={
                    "action_show_more_info": {
                        "label": "Show Traceback",
                        "tooltip": "Show complete traceback",
                        "text": traceback.format_exc()
                    }
                })

            raise err
        finally:
            abc_archive.close()

    def accept(self, task_settings, item):
        """
        Method called by the publisher to determine if an item is of any
        interest to this plugin. Only items matching the filters defined via the
        item_filters property will be presented to this method.

        A publish task will be generated for each item accepted here. Returns a
        dictionary with the following booleans:

            - accepted: Indicates if the plugin is interested in this value at
                all. Required.
            - enabled: If True, the plugin will be enabled in the UI, otherwise
                it will be disabled. Optional, True by default.
            - visible: If True, the plugin will be visible in the UI, otherwise
                it will be hidden. Optional, True by default.
            - checked: If True, the plugin will be checked in the UI, otherwise
                it will be unchecked. Optional, True by default.

        :param item: Item to process

        :returns: dictionary with boolean keys accepted, required and enabled
        """

        # Run the parent acceptance method
        accept_data = super(MayaPublishGeometryPlugin, self).accept(task_settings, item)
        if not accept_data.get("accepted"):
            return accept_data

        # check that the AbcExport command is available!
        if not mel.eval("exists \"AbcExport\""):
            self.logger.debug(
                "Item not accepted because alembic export command 'AbcExport' "
                "is not available. Perhaps the plugin is not enabled?"
            )
            accept_data["accepted"] = False

        # TODO: if already exported geo exists, don't re-export

        # return the accepted info
        return accept_data

    def validate(self, task_settings, item):
        """
        Validates the given item to check that it is ok to publish. Returns a
        boolean to indicate validity.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        :returns: True if item is valid, False otherwise.
        """
        # check that there is still geometry in the scene:
        if not cmds.ls(geometry=True, noIntermediate=True):
            error_msg = (
                "Validation failed because there is no geometry in the scene "
                "to be exported. You can uncheck this plugin or create "
                "geometry to export to avoid this error."
            )
            self.logger.error(error_msg)
            raise TankError(error_msg)

        return super(MayaPublishGeometryPlugin, self).validate(task_settings, item)

    def publish_files(self, task_settings, item, publish_path):
        """
        Overrides the inherited method for copying the work file to the publish location
        to instead export out the scene geometry to the publish_path location.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        :param publish_path: The output path to publish files to
        """
        publisher = self.parent

        # set the alembic args that make the most sense when working with Mari.
        # These flags will ensure the export of an Alembic file that contains
        # all visible geometry from the current scene together with UV's and
        # face sets for use in Mari.
        alembic_args = [
            # only renderable objects (visible and not templated)
            "-renderableOnly",
            # write shading group set assignments (Maya 2015+)
            "-writeFaceSets",
            # apply euler filter to avoid gimbal lock issues
            "-eulerFilter"
        ]

        # find the animated frame range to use:
        start_frame, end_frame = _find_scene_animation_range()
        if start_frame and end_frame:
            alembic_args.append("-fr %d %d" % (start_frame, end_frame))

        # Creating a temporary file on the publish path, where the alembic from maya would be
        # exported
        publish_file_temp = tempfile.NamedTemporaryFile(mode='w+b',
                                                        suffix='.abc',
                                                        prefix='tmp',
                                                        dir="/var/tmp/",
                                                        delete=True)

        publish_path_temp = publish_file_temp.name.replace("\\", "/")

        # Set the output path:
        # Note: The AbcExport command expects forward slashes!
        alembic_args.append("-file %s" % publish_path_temp)

        # Set the root node to be exported
        alembic_args.append("-root %s" % item.get_property("lod_full_name"))

        # Add args based on publish settings
        if task_settings["Export UVs"].value:
            alembic_args.append("-uvWrite -writeCreases -writeUVSets")
        if task_settings["Export WorldSpace"].value:
            alembic_args.append("-worldSpace")
        if task_settings["Strip Namespace"].value:
            alembic_args.append("-stripNamespaces")

        # build the export command.  Note, use AbcExport -help in Maya for
        # more detailed Alembic export help
        abc_export_cmd = ("AbcExport -j \"%s\"" % " ".join(alembic_args))

        # ...and execute it:
        try:
            # ensure the publish folder exists:
            publish_folder = os.path.dirname(publish_path)
            ensure_folder_exists(publish_folder)

            publisher.log_debug("Executing command: %s" % abc_export_cmd)
            cmds.refresh(suspend=True)
            mel.eval(abc_export_cmd)
            cmds.refresh(suspend=False)
        except Exception as e:
            raise Exception("Failed to export Geometry: %s" % e)

        self.logger.debug(
            "Exported group %s to '%s'." % (item.properties.fields["node"], publish_path)
        )

        # Renaming top group name to be the asset name, in exported alembic.
        asset_name = item.context.entity["name"]
        self._rename_abc_top_group(publish_path_temp, str(publish_path), asset_name)
        publish_file_temp.close()

        return [publish_path]


def _find_scene_animation_range():
    """
    Find the animation range from the current scene.
    """
    # look for any animation in the scene:
    animation_curves = cmds.ls(typ="animCurve")

    # if there aren't any animation curves then just return
    # a single frame:
    if not animation_curves:
        return 1, 1

    # something in the scene is animated so return the
    # current timeline.  This could be extended if needed
    # to calculate the frame range of the animated curves.
    start = int(cmds.playbackOptions(q=True, min=True))
    end = int(cmds.playbackOptions(q=True, max=True))

    return start, end
