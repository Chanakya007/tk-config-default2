# Copyright (c) 2015 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Hook that loads defines all the available actions, broken down by publish type. 
"""

import glob
import os
import re
import pymel.core as pm
import maya.cmds as cmds
import maya.mel as mel
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()


class CustomMayaActions(HookBaseClass):

    def generate_actions(self, sg_data, actions, ui_area):
        """
        Returns a list of action instances for a particular object.
        The data returned from this hook will be used to populate the
        actions menu.

        The mapping between Shotgun objects and actions are kept in a different place
        (in the configuration) so at the point when this hook is called, the app
        has already established *which* actions are appropriate for this object.

        This method needs to return detailed data for those actions, in the form of a list
        of dictionaries, each with name, params, caption and description keys.

        The ui_area parameter is a string and indicates where the item is to be shown.

        - If it will be shown in the main browsing area, "main" is passed.
        - If it will be shown in the details area, "details" is passed.

        :param sg_data: Shotgun data dictionary with all the standard shotgun fields.
        :param actions: List of action strings which have been defined in the app configuration.
        :param ui_area: String denoting the UI Area (see above).
        :returns List of dictionaries, each with keys name, params, caption and description
        """
        app = self.parent

        # get the existing action instances
        action_instances = super(CustomMayaActions, self).generate_actions(sg_data, actions, ui_area)

        if "texture_node_with_frames" in actions:
            action_instances.append({"name": "texture_node_with_frames",
                                     "params": None,
                                     "caption": "Create Texture Node (Frames)",
                                     "description": "Creates a file texture node, which reads the frames as per timeline for the selected item.."})

        return action_instances

    def execute_action(self, name, params, sg_data):
        """
        Execute a given action. The data sent to this be method will
        represent one of the actions enumerated by the generate_actions method.

        :param name: Action name string representing one of the items returned by generate_actions.
        :param params: Params data, as specified by generate_actions.
        :param sg_data: Shotgun data dictionary
        :returns: No return value expected.
        """

        app = self.parent

        # call the actions from super
        super(CustomMayaActions, self).execute_action(name, params, sg_data)

        # resolve path
        # toolkit uses utf-8 encoded strings internally and Maya API expects unicode
        # so convert the path to ensure filenames containing complex characters are supported
        path = self.get_publish_path(sg_data).decode("utf-8")

        if name == "texture_node_with_frames":
            self._create_texture_node_with_frames(path, sg_data)

    ##############################################################################################################
    # helper methods which can be subclassed in custom hooks to fine tune the behaviour of things

    def _create_texture_node_with_frames(self, path, sg_publish_data):
        """
        Create a file texture node for a texture

        :param path:             Path to file.
        :param sg_publish_data:  Shotgun data dictionary with all the standard publish fields.
        :returns:                The newly created file node
        """

        # use mel command instead, since that creates the corresponding place2dtexture node with connections
        # file_node = cmds.shadingNode('file', asTexture=True)
        file_node = mel.eval('createRenderNodeCB -as2DTexture "" file ""')

        has_frame_spec, path = self._find_first_frame(path)
        cmds.setAttr("%s.fileTextureName" % file_node, path, type="string")

        if has_frame_spec:
            # setting the frame extension flag will create an expression to use
            # the current frame.
            cmds.setAttr("%s.useFrameExtension" % (file_node,), 1)

            # Fetching the map type name from the file name at the path
            entity_name = sg_publish_data["entity"]["name"]
            pub_name = sg_publish_data["name"]
            file_node_name = "{0}{1}".format(entity_name, pub_name.split(entity_name)[-1])
            # Renaming the file node created to the map being loaded
            # Overriding the file_node variable to return the newly assigned name
            file_node = cmds.rename(file_node, file_node_name)

        return file_node

    def _create_texture_node(self, path, sg_publish_data):
        """
        Create a file texture node for a texture

        :param path:             Path to file.
        :param sg_publish_data:  Shotgun data dictionary with all the standard publish fields.
        :returns:                The newly created file node
        """

        # use mel command instead, since that creates the corresponding place2dtexture node with connections
        # file_node = cmds.shadingNode('file', asTexture=True)
        file_node = mel.eval('createRenderNodeCB -as2DTexture "" file ""')

        has_frame_spec, path = self._find_first_frame(path)

        # use the first frame instead of %04d, else maya errors out with "File Doesn't exist".
        cmds.setAttr("%s.fileTextureName" % file_node, path, type="string")

        # Fetching the map type name from the file name at the path
        entity_name = sg_publish_data["entity"]["name"]
        pub_name = sg_publish_data["name"]
        file_node_name = "{0}{1}".format(entity_name, pub_name.split(entity_name)[-1])
        # Renaming the file node created to the map being loaded
        # Overriding the file_node variable to return the newly assigned name
        file_node = cmds.rename(file_node, file_node_name)

        return file_node

    def _create_udim_texture_node(self, path, sg_publish_data):
        """
        Create a file texture node for a UDIM (Mari) texture

        :param path:             Path to file.
        :param sg_publish_data:  Shotgun data dictionary with all the standard publish fields.
        :returns:                The newly created file node
        """
        # create the normal file node:
        file_node = self._create_texture_node(path, sg_publish_data)
        if file_node:
            # path is a UDIM sequence so set the uv tiling mode to 3 ('UDIM (Mari)')
            cmds.setAttr("%s.uvTilingMode" % file_node, 3)
            # and generate a preview:
            mel.eval("generateUvTilePreview %s" % file_node)
        return file_node

    def _find_first_frame(self, path):
        has_frame_spec = False
        # replace any %0#d format string with a glob character. then just find
        # an existing frame to use. example %04d => *
        frame_pattern = re.compile("(%0\dd)")
        frame_match = re.search(frame_pattern, path)
        if frame_match:
            has_frame_spec = True
            frame_spec = frame_match.group(1)
            glob_path = path.replace(frame_spec, "*")
            frame_files = glob.glob(glob_path)
            if frame_files:
                return has_frame_spec, frame_files[0]
            else:
                return has_frame_spec, None
        return has_frame_spec, path

    def _create_image_plane(self, path, sg_publish_data):
        """
        Create a file texture node for a UDIM (Mari) texture

        :param path: Path to file.
        :param sg_publish_data: Shotgun data dictionary with all the standard
            publish fields.
        :returns: The newly created file node
        """

        app = self.parent

        has_frame_spec, path = self._find_first_frame(path)
        if not path:
            self.parent.logger.error(
                "Could not find file on disk for published file path %s" %
                (path,)
            )
            return

        # create an image plane for the supplied path, visible in all views
        (img_plane, img_plane_shape) = cmds.imagePlane(
            fileName=path,
            showInAllViews=True
        )
        app.logger.debug(
            "Created image plane %s with path %s" %
            (img_plane, path)
        )

        if has_frame_spec:
            # setting the frame extension flag will create an expression to use
            # the current frame.
            cmds.setAttr("%s.useFrameExtension" % (img_plane_shape,), 1)
