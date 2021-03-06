# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import copy
import maya.cmds as cmds
import pymel.core as pm

import sgtk
from sgtk import TankError
from sgtk.platform.qt import QtGui
from sgtk.platform.settings import resolve_setting_expression
from sgtk.util import filesystem


HookBaseClass = sgtk.get_hook_baseclass()

GROUP_NODES = ['WORLDSCALE',
               'SET_TO_WORLD',
               'TRACK_GEO']

CAMERA_NAME = 'CAM'

DEFAULT_CAMERAS = ['persp',
                   'top',
                   'front',
                   'side']

CAM_TASK_SUFFIX = "cam"
UNDIST_TASK_SUFFIX = "undist"


class MayaPublishSessionIntegPlugin(HookBaseClass):
    """
    Inherits from MayaPublishFilesPlugin
    """

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """

        desc = super(MayaPublishSessionIntegPlugin, self).description

        return desc + "<br><br>" + """
        Additional integ validations will be run before a file is published.
        """

    def _check_frame_range_with_shotgun(self, item):
        """
        Checks whether frame range is in sync with shotgun.

        :param item: Item to process
        :return: True if yes False otherwise
        """
        context = item.context
        entity = context.entity

        # checking entity validity
        if entity:
            frame_range_app = self.parent.engine.apps.get("tk-multi-setframerange")
            if not frame_range_app:
                # return valid for asset/sequence entities
                self.logger.warning("Unable to find tk-multi-setframerange app. "
                                    "Not validating frame range.")
                return True

            sg_entity_type = entity["type"]
            sg_filters = [["id", "is", entity["id"]]]
            in_field = frame_range_app.get_setting("sg_in_frame_field")
            out_field = frame_range_app.get_setting("sg_out_frame_field")
            fields = [in_field, out_field]

            # get the field information from shotgun based on Shot
            # sg_cut_in and sg_cut_out info will be on Shot entity, so skip in case this info is not present
            # or if the sg_head_in or sg_tail_out is empty, skip the check
            data = self.sgtk.shotgun.find_one(sg_entity_type, filters=sg_filters, fields=fields)
            if in_field not in data or out_field not in data:
                return True
            elif in_field is None or out_field is None:
                return True

            # Check if playback_start or animation_start is not in sync with shotgun
            # Similarly if animation_start or animation_start is not in sync with shotgun
            playback_start = pm.playbackOptions(q=True, minTime=True)
            playback_end = pm.playbackOptions(q=True, maxTime=True)
            
            animation_start = pm.playbackOptions(q=True, animationStartTime=True)
            animation_end = pm.playbackOptions(q=True, animationEndTime=True)
            
            if playback_start != data[in_field] or playback_end != data[out_field]:
                self.logger.warning("Frame range not synced with Shotgun.")
                QtGui.QMessageBox.warning(None, "Frame range mismatch!",
                                          "WARNING! Frame range not synced with Shotgun.")
                return True
            
            if animation_start != data[in_field] or animation_end != data[out_field]:
                self.logger.warning("Frame range not synced with Shotgun.")
                QtGui.QMessageBox.warning(None, "Frame range mismatch!",
                                          "WARNING! Frame range not synced with Shotgun.")
                return True
            return True
        return True


    def _no_nodes_outside_track_geo(self):
        """
        Checks that there are no nodes, apart from groups and camera, outside of TRACK_GEO node
        
        :return: True if yes False otherwise
        """
        children = cmds.listRelatives('TRACK_GEO', c=True)
        # Subtracting group nodes, cameras and child nodes of TRACK_GEO from the list of dag nodes.
        # This is to get extra nodes present outside TRACK_GEO
        if children:
            extras = list(set(cmds.ls(tr=True, dag=True)) - set(GROUP_NODES) - set(cmds.listCameras()) - set(children))
        else:
            extras = list(set(cmds.ls(tr=True, dag=True)) - set(GROUP_NODES) - set(cmds.listCameras()))

        if extras:
            self.logger.error("Nodes present outside TRACK_GEO.",
                              extra={
                                  "action_show_more_info": {
                                      "label": "Show Info",
                                      "tooltip": "Show the extra nodes",
                                      "text": "Nodes outside TRACK_GEO:\n{}".format("\n".join(extras))
                                  }
                              }
                              )
            return False
        return True


    def _check_locked_channels_track_geo(self):
        """
        Check that there are no locked attributes in all nodes under the group TRACK_GEO.
        
        :param nodes: list of nodes under TRACK_GEO
        :return: True if yes False otherwise
        """
        children = cmds.listRelatives('TRACK_GEO', c=True)
        if children:
            locked = ""
            for node in children:
                # For each node, list out attributes which are locked
                lock_per_node = cmds.listAttr(node, l=True)
                if lock_per_node:
                    locked += "\n" + node + ": " + ", ".join(lock_per_node)
            # If there are locked channels, error message with node name and locked attribute(s).
            if locked:
                self.logger.error("Locked channels detected.",
                                  extra={
                                      "action_show_more_info": {
                                          "label": "Show Info",
                                          "tooltip": "Show the node and locked channels",
                                          "text": "Locked channels:\n{}".format(locked)
                                      }
                                  })
                return False
            return True
        return True


    def _track_geo_child_naming(self):
        """Checks if the name of nodes under TRACK_GEO are prefixed with 'integ_'.
            :param:
                track_geo: nodes under TRACK_GEO
            :return: True if yes False otherwise
        """
        # Nodes under TRACK_GEO group
        children = cmds.listRelatives('TRACK_GEO', c=True)
        error_names = ""
        # if there are nodes under TRACK_GEO, check for one without prefix "integ_"
        if children:
            for child in children:
                # If the name doesn't start with integ_ add node name to errorNames
                if child[:6] != "integ_":
                    error_names += "\n" + child
        if error_names:
            self.logger.error("Incorrect Naming! Node name should start with integ_.",
                              extra={
                                  "action_show_more_info": {
                                      "label": "Show Info",
                                      "tooltip": "Show the node with incorrect naming",
                                      "text": "Nodes with incorrect naming:\n{}".format(error_names)
                                  }
                              }
                              )
            return False
        return True


    def _check_hierarchy(self, group_nodes):
        """Checks the hierarchy of group nodes in the scene.
            :param:
                group_nodes: the list of nodes in the scene
            :return: True if yes False otherwise
        """
        for name in range(len(group_nodes) - 1):
            # Listing children of group nodes
            children = cmds.listRelatives(group_nodes[name], c=True)
            # group_nodes is arranged in hierarchical order i.e. the next node should be the child of previous
            if children and (group_nodes[name + 1] in children):
                if name == 'SET_TO_WORLD' and 'CAM' in children:
                    continue
            else:
                hierarchy = "WORLDSCALE\n|__SET_TO_WORLD\n" + "    " + "|__TRACK_GEO\n" + "    " + "|__CAM"
                self.logger.error("Incorrect hierarchy.",
                                  extra={
                                      "action_show_more_info": {
                                          "label": "Show Info",
                                          "tooltip": "Show the required hierarchy",
                                          "text": "Required hierarchy:\n\n{}".format(hierarchy)
                                      }
                                  }
                                  )
                return False
        return True


    def _connected_image_plane(self):
        camshape = cmds.listRelatives(CAMERA_NAME, s=True, c=True)[0]
        connections = cmds.listConnections(camshape + '.imagePlane', source=True, type='imagePlane')
        if not connections:
            self.logger.error("Image plane not attached to CAM.")
            return False
        return True


    def _camera_naming(self):
        """Checks the naming of the camera.
            :param:
                group_nodes: The list of nodes that should be in the scene. This will be
                used to check node hierarchy once camera naming is validated.
            :return: True if yes False otherwise
        """
        # Look for all the cameras present in the scene
        all_cameras = cmds.listCameras()
        # Remove the default_cameras from the list
        main_cam = list(set(all_cameras) - set(DEFAULT_CAMERAS))
        if main_cam:
            if len(main_cam) > 1:
                # Checking if more than one CAM present
                self.logger.error("More the one camera detected. Only CAM should be present.")
                return False
            elif main_cam[0] != CAMERA_NAME:
                # Validating camera name
                self.logger.error("Incorrect camera name! Should be CAM.")
                return False
        else:
            self.logger.error("Camera (CAM) not present in the scene.")
            return False
        return True


    def _node_naming(self, groups):
        """Checking if the established group node names have not been tampered with.
            :param:
                group_nodes: group nodes to be present in the scene
                groups: group nodes that are actually present
            :return: True if yes False otherwise
        """
        # Check for extra group nodes apart from the ones in group_nodes
        extras = list(set(groups) - set(GROUP_NODES))
        # check for any group nodes apart from the once mentioned
        if extras:
            self.logger.error("Incorrect naming or extra group nodes present in the scene.",
                              extra={
                                  "action_show_more_info": {
                                      "label": "Show Info",
                                      "tooltip": "Show the conflicting group nodes",
                                      "text": "Please check the group nodes:\n{}".format("\n".join(extras)) +
                                              "\n\nOnly following group nodes should be present:\n{}".format(
                                                  "\n".join(GROUP_NODES))
                                  }
                              }
                              )
            return False
        # check if any of the required group nodes are missing
        elif not set(GROUP_NODES).issubset(set(groups)):
            self.logger.error("Please ensure all the group nodes are present.",
                              extra={
                                  "action_show_more_info": {
                                      "label": "Show Info",
                                      "tooltip": "Group nodes",
                                      "text": "Following group nodes should be present:\n{}".format(
                                          "\n".join(GROUP_NODES))
                                  }
                              }
                              )
            return False
        return True


    @staticmethod
    def _is_group_transform(node=None):
        """
        Check whether all non-leaf nodes under the given node are transform nodes.

        :param node:    Node whose hierarchy needs to be checked
        :return:        True if only transform nodes have children, else False
        """
        if cmds.nodeType(node) != "transform":
            return False

        children = cmds.listRelatives(node, c=True)
        if not children:
            return True

        for c in children:
            if cmds.nodeType(c) != 'transform':
                return False
        else:
            return True

    def _find_latest_nuke_workfile_version(self, fields):
        engine = self.parent.engine

        workfiles_app = self.parent.engine.apps.get("tk-multi-workfiles2")
        if not workfiles_app:
            # this should never happen?
            self.logger.error("tk-multi-workfiles2 is not configured for this environment!")
            return 0

        # copied from tk-multi-workfiles2.file_save_form._generate_path()
        # TODO: expose this somehow? used in multiple places
        work_template_setting = workfiles_app.settings.get('template_work')
        work_template_name = resolve_setting_expression(work_template_setting.raw_value,
                                                        "tk-nuke", engine.env.name)
        work_template = self.sgtk.templates[work_template_name]

        publish_template_setting = workfiles_app.settings.get('template_publish')
        publish_template_name = resolve_setting_expression(publish_template_setting.raw_value,
                                                           "tk-nuke", engine.env.name)
        publish_template = self.sgtk.templates[publish_template_name]

        file_item_module = workfiles_app.import_module('tk_multi_workfiles.file_item')
        file_finder_module = workfiles_app.import_module('tk_multi_workfiles.file_finder')

        file_key = file_item_module.FileItem.build_file_key(fields, work_template)
        try:
            finder = file_finder_module.FileFinder()
            files = finder.find_files(work_template,
                                      publish_template,
                                      self.parent.context,
                                      file_key) or []
        except TankError, e:
            raise TankError("Failed to find files for this work area: %s" % e)
        file_versions = [f.version for f in files]
        max_version = max(file_versions or [0])
        return max_version

    def _check_undist_status(self, item):
        context = item.context
        task_name = context.task['name']

        undist_task_name = task_name.replace(CAM_TASK_SUFFIX, UNDIST_TASK_SUFFIX)
        undist_task = self.sgtk.shotgun.find_one("Task", [["content", "is", undist_task_name],
                                                          ["entity", "is", context.entity]])
        if undist_task:
            # find latest published version
            latest_pub_version = 0
            order = [{'field_name': 'version_number', 'direction': 'desc'}]
            pub_files = self.sgtk.shotgun.find("PublishedFile", [["task", "is", undist_task]],
                                               fields=["version_number"],
                                               order=order, limit=1)
            if pub_files:
                latest_pub_version = pub_files[0]["version_number"]

            fields = context.as_template_fields()
            fields["name"] = undist_task_name
            latest_work_version = self._find_latest_nuke_workfile_version(fields)

            if latest_work_version > latest_pub_version:
                self.logger.warning("Task {}: latest published version is {}, but version {} "
                                    "found in workspace".format(undist_task_name, latest_pub_version,
                                                                latest_work_version))
                QtGui.QMessageBox.warning(None, "Task {} unpublished!".format(undist_task_name),
                                          "For task {}, you seem to have unpublished version `{}` " \
                                          "in your workspace.\nPlease publish this if needed. " \
                                          "Latest published version is `{}`.".format(
                                              undist_task_name, latest_work_version,
                                              latest_pub_version)
                                          )
        else:
            self.logger.warning("No task {} found linked to entity {}. "
                                "Not checking for unpublished files!".format(undist_task_name, context.entity))
        return True


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

        status = super(MayaPublishSessionIntegPlugin, self).validate(task_settings, item)
        
        # Checks for the scene file
        if item.context.entity["type"] == "Shot":
            task_name = item.context.task['name']
            task_name_suffix = task_name.split("_")[-1]
            if task_name_suffix == CAM_TASK_SUFFIX:
                all_dag_nodes = cmds.ls(dag=True, sn=True)
                groups = [g for g in all_dag_nodes if self._is_group_transform(g)]

                nodes_status = self._node_naming(groups) and \
                               self._check_hierarchy(groups) and \
                               self._track_geo_child_naming() and \
                               self._check_locked_channels_track_geo() and \
                               self._no_nodes_outside_track_geo() and \
                               self._check_frame_range_with_shotgun(item)
                cam_status = self._camera_naming() and self._connected_image_plane()
                undist_status = self._check_undist_status(item)

                status = nodes_status and cam_status and undist_status and status
            elif task_name_suffix != UNDIST_TASK_SUFFIX: # this is a matchmove task
                status = self._check_frame_range_with_shotgun(item)

        return status

    def publish_files(self, task_settings, item, publish_path):
        """
        This method publishes (copies) the item's path property to the publish location.
        For session override this to do cleanup and save to publish location instead,
        then discard the changes done during cleanup from the workfile so that they are
        not preserved while versioning up.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        :param publish_path: The output path to publish files to
        """

        path = copy.deepcopy(item.properties.get("path"))
        if not path:
            raise KeyError("Base class implementation of publish_files() method requires a 'path' property.")

        # Save to publish path
        self.import_references(item)
        self._save_session(publish_path, item.properties.get("publish_version"), item)

        # Determine if we should seal the copied files or not
        seal_files = item.properties.get("seal_files", False)
        if seal_files:
            filesystem.seal_file(publish_path)

        # Reopen work file and reset item property path, context
        cmds.file(new=True, force=True)
        cmds.file(path, open=True, force=True)

        item.properties.path = path
        self.parent.engine.change_context(item.context)

    def import_references(self, item):
        # import all references in the file
        self.parent.logger.info("Importing references in the current session...")
        references = pm.ls(references=1)
        for reference in references:
            cmds.file(pm.referenceQuery(reference, f=True), importReference=True)
