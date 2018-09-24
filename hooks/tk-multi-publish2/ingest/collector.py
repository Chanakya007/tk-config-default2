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
import datetime
import traceback
import pprint

import sgtk
import tank
from tank_vendor import yaml

HookBaseClass = sgtk.get_hook_baseclass()

NOTES_ENTITY_FILTER = "notes.entity.*"

# This is a dictionary of fields in snapshot from manifest and it's corresponding field on the item.
DEFAULT_MANIFEST_SG_MAPPINGS = {
    "id": "sg_snapshot_id",
    "notes": "description",
    "name": "snapshot_name",
    "user": "snapshot_user",
    "version": "snapshot_version",
    # notes related keys
    "body": "content"
}


class IngestCollectorPlugin(HookBaseClass):
    """
    Collector that operates on the current set of ingestion files. Should
    inherit from the basic collector hook.

    This instance of the hook uses manifest_file_name, default_entity_type, default_snapshot_type from app_settings.

    """

    @property
    def settings_schema(self):
        """
        Dictionary defining the settings that this collector expects to receive
        through the settings parameter in the process_current_session and
        process_file methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default_value": "default_value",
                    "description": "One line description of the setting"
            }

        The type string should be one of the data types that toolkit accepts as
        part of its environment configuration.
        """
        schema = super(IngestCollectorPlugin, self).settings_schema
        items_schema = schema["Item Types"]["values"]["items"]
        items_schema["default_snapshot_type"] = {
            "type": "str",
            "description": "",
            "allows_empty": True,
            "default_value": self.parent.settings["default_snapshot_type"],
        }
        items_schema["default_fields"] = {
            "type": dict,
            "values": {
                "type": "str",
            },
            "allows_empty": True,
            "default_value": {},
            "description": "Default fields to use, with this item"
        }
        schema["Manifest SG Mappings"] = {
            "type": "dict",
            "values": {
                "type": "str",
            },
            "default_value": DEFAULT_MANIFEST_SG_MAPPINGS,
            "allows_empty": True,
            "description": "Mapping of keys in Manifest to SG template keys."
        }
        return schema

    def _get_item_info(self, settings, path, is_sequence):
        """
        Return a tuple of display name, item type, and icon path for the given
        filename.

        The method will try to identify the file as a common file type. If not,
        it will use the mimetype category. If the file still cannot be
        identified, it will fallback to a generic file type.

        :param dict settings: Configured settings for this collector
        :param path: The file path to identify type info for

        :return: A dictionary of information about the item to create::

            # path = "/path/to/some/file.0001.exr"

            {
                "item_type": "file.image.sequence",
                "type_display": "Rendered Image Sequence",
                "icon_path": "/path/to/some/icons/folder/image_sequence.png",
            }

        The item type will be of the form `file.<type>` where type is a specific
        common type or a generic classification of the file.
        """

        item_info = super(IngestCollectorPlugin, self)._get_item_info(settings, path, is_sequence)

        # from the above item_type, check if default_snapshot_type is parent settings default_snapshot_type
        item_type = item_info["item_type"]

        item_settings = settings["Item Types"].value.get(item_type)
        if item_settings:
            default_snapshot_type = item_settings.get("default_snapshot_type")
            default_fields = item_settings.get("default_fields")

            item_info["default_snapshot_type"] = default_snapshot_type
            item_info["default_fields"] = default_fields
        # item not found in our settings
        else:
            item_info["default_snapshot_type"] = self.parent.settings["default_snapshot_type"]
            item_info["default_fields"] = {}

        return item_info

    def _add_note_item(self, settings, parent_item, attachments, is_sequence=False, seq_files=None):
        """
        Process the supplied list of attachments, and create a note item.

        :param dict settings: Configured settings for this collector
        :param parent_item: parent item instance
        :param attachments: List of attachment file paths

        :returns: The item that was created
        """

        publisher = self.parent

        item_types = settings["Item Types"].value

        # default values used if no specific type can be determined
        type_display = "File"
        item_type = "file.unknown"
        work_path_template = None
        icon_path = "{self}/hooks/icons/file.png"

        # since we only need one of the attachment frames to figure out the context
        path = attachments.keys()[0]
        display_name = publisher.util.get_publish_name(path)

        # # fetch all the settings of NOTES_ENTITY
        # if NOTES_ENTITY_FILTER in item_types:
        #     type_info = item_types[NOTES_ENTITY_FILTER]
        #
        #     type_display = type_info["type_display"]
        #     icon_path = type_info["icon"]
        #     work_path_template = type_info.get("work_path_template")
        #     item_type = NOTES_ENTITY_FILTER
        # else:
        #     self.logger.error("Notes item is not setup for the collector, can't ingest notes!")

        # expand the icon path
        icon_path = publisher.expand_path(icon_path)

        # Define the item's properties
        properties = {}

        # set the path and is_sequence properties for the plugins to use
        properties["path"] = path
        properties["is_sequence"] = is_sequence

        # If a sequence, add the sequence path
        if is_sequence:
            properties["sequence_paths"] = seq_files

        if work_path_template:
            properties["work_path_template"] = work_path_template

        # build the context of the item
        context = self._get_item_context_from_path(parent_item, properties, path)

        # resolve the new plugin settings
        # these are the correct settings for this context
        plugin_settings = self.plugin.build_settings_dict(context)

        # I did find a work-around to replacing env manually by building new settings dict, but it still feels patchy.
        # TODO: Find a better way to support work_path_template based objects, which have similar extensions.
        # i don't have any other way to resolve the correct template name
        # since initially all the settings, resolve at the context of publisher
        # path_env_name = self.tank.execute_core_hook(tank.platform.constants.PICK_ENVIRONMENT_CORE_HOOK_NAME,
        #                                             context=context)
        # publisher_env_name = self.tank.execute_core_hook(tank.platform.constants.PICK_ENVIRONMENT_CORE_HOOK_NAME,
        #                                                  context=publisher.context)

        tmpl_obj = self.sgtk.template_from_path(path)
        template_name = None

        if tmpl_obj:
            template_name = tmpl_obj.name
            # template_name = template_name.replace(path_env_name, publisher_env_name)

        # extract the components of the supplied path
        file_info = publisher.util.get_file_path_components(path)
        extension = file_info["extension"]

        extension_itemtype_mapping = dict()

        for item_type, type_info in plugin_settings["Item Types"].value.iteritems():
            for ext in type_info["extensions"]:
                if ext not in extension_itemtype_mapping:
                    extension_itemtype_mapping[ext] = list()

                extension_itemtype_mapping[ext].append(item_type)

        if extension in extension_itemtype_mapping:
            for item_type in extension_itemtype_mapping[extension]:
                type_info = plugin_settings["Item Types"].value[item_type]

                work_path_template = type_info.get("work_path_template")

                # template validation to check if the path matches work path template
                # this will allow us to maintain multiple item types with similar extensions
                # which can be used to specialize certain paths, and map them to different publish paths or even plugins
                # eg. jpg's can be avidref, notes, or undist plates and all of them are treated differently.
                if work_path_template == template_name:
                    # we found our match
                    # type_display, icon path, and work_path_template.
                    type_display = type_info["type_display"]
                    icon_path = type_info["icon"]
                    work_path_template = type_info.get("work_path_template")

                    break
                else:
                    # let's keep looping to find the next possible extension that matches us
                    work_path_template = None
                    continue

        # create and populate the item
        file_item = parent_item.create_item(
            item_type,
            type_display,
            display_name,
            collector=self.plugin,
            context=context,
            properties=properties
        )

        # Set the icon path
        file_item.set_icon_from_path(icon_path)

        # set the thumbnail as preview
        file_item.set_thumbnail_from_path(path)
        file_item.thumbnail_enabled = False

        # only for the notes item preserve the settings, this will be used in get_item_info!
        file_item.properties.note_item_settings = plugin_settings["Item Types"].value[item_type]

        return file_item

    def _resolve_work_path_template(self, properties, path):
        """
        Resolve work_path_template from the properties.
        The signature uses properties, so that it can resolve the template even if the item object hasn't been created.

        :param properties: properties that have/will be used to build item object.
        :param path: path to be used to get the templates, using template_from_path,
         in this class we use os.path.basename of the path.
        :return: Name of the template.
        """

        # try using file name for resolving templates
        work_path_template = super(IngestCollectorPlugin, self)._resolve_work_path_template(properties,
                                                                                            os.path.basename(path))
        # try using the full path for resolving templates
        if not work_path_template:
            work_path_template = super(IngestCollectorPlugin, self)._resolve_work_path_template(properties, path)

        return work_path_template

    def process_file(self, settings, parent_item, path):
        """
        Analyzes the given file and creates one or more items
        to represent it.

        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance
        :param path: Path to analyze

        :returns: The main item that was created, or None if no item was created
            for the supplied path
        """

        publisher = self.parent

        file_items = list()

        # handle Manifest files, Normal files and folders differently
        if os.path.isdir(path):
            items = self._collect_folder(settings, parent_item, path)
            if items:
                file_items.extend(items)
        else:
            if publisher.settings["manifest_file_name"] in os.path.basename(path):
                items = self._collect_manifest_file(settings, parent_item, path)
                if items:
                    file_items.extend(items)
            else:
                item = self._collect_file(settings, parent_item, path)
                if item:
                    file_items.append(item)

        # make sure we have snapshot_type field in all the items!
        # this is to make sure that on publish we retain this field to figure out asset creation is needed or not.
        for file_item in file_items:
            fields = file_item.properties["fields"]
            item_info = self._get_item_info(settings=settings,
                                            path=file_item.properties["path"],
                                            is_sequence=file_item.properties["is_sequence"])

            # check for default fields those are only present on notes item currently.
            if "note_item_settings" in file_item.properties:
                default_fields = file_item.properties["note_item_settings"]["default_fields"]
                for key, value in default_fields.iteritems():
                    if key not in fields:
                        fields[key] = value

            if "snapshot_type" not in fields:

                fields["snapshot_type"] = item_info["default_snapshot_type"]
                # CDL files should always be published as Asset entity with nuke_avidgrade asset_type
                # this is to match organic, and also for Avid grade lookup on shotgun
                # this logic has been moved to _get_item_info by defining default_snapshot_type for each item type
                # if file_item.type == "file.cdl":
                #     fields["snapshot_type"] = "nuke_avidgrade"

                self.logger.info(
                    "Injected snapshot_type field for item: %s" % file_item.name,
                    extra={
                        "action_show_more_info": {
                            "label": "Show Info",
                            "tooltip": "Show more info",
                            "text": "Updated fields:\n%s" %
                                    (pprint.pformat(file_item.properties["fields"]))
                        }
                    }
                )

        return file_items

    def _process_manifest_file(self, settings, path):
        """
        Do the required processing on the yaml file, sanitisation or validations.
        conversions mentioned in Manifest Types setting of the collector hook.

        :param path: path to yaml file
        :return: list of processed snapshots, in the format
        [{file(type of collect method to run):
            {'fields': {'context_type': 'maya_model',
                        'department': 'model',
                        'description': 'n/a',
                        'instance_name': None,
                        'level': None,
                        'snapshot_name': 'egypt_riser_a',
                        'snapshot_type': 'maya_model',
                        'sg_snapshot_id': 1002060803L,
                        'subcontext': 'hi',
                        'type': 'asset',
                        'snapshot_user': 'rsariel',
                        'snapshot_version': 1},
             'files': {'/dd/home/gverma/work/SHARED/MODEL/enviro/egypt_riser_a/hi/maya_model/egypt_riser_a_hi_tag_v001.xml': ['tag_xml'],
                       '/dd/home/gverma/work/SHARED/MODEL/enviro/egypt_riser_a/hi/maya_model/egypt_riser_a_hi_transform_v001.xml': ['transform_xml'],
                       '/dd/home/gverma/work/SHARED/MODEL/enviro/egypt_riser_a/hi/maya_model/egypt_riser_a_hi_v001.mb': ['main', 'mayaBinary']}
            }
        }]
        """

        processed_snapshots = list()
        manifest_mappings = settings['Manifest SG Mappings'].value
        # yaml file stays at the base of the package
        base_dir = os.path.dirname(path)

        snapshots = list()
        notes = list()

        with open(path, 'r') as f:
            try:
                contents = yaml.load(f)
                snapshots = contents["snapshots"]
                if "notes" in contents:
                    notes = contents["notes"]
            except Exception:
                self.logger.error(
                    "Failed to read the manifest file %s" % path,
                    extra={
                        "action_show_more_info": {
                            "label": "Show Error Log",
                            "tooltip": "Show the error log",
                            "text": traceback.format_exc()
                        }
                    }
                )
                return processed_snapshots

        for snapshot in snapshots:
            # first replace all the snapshot with the Manifest SG Mappings
            data = dict()
            data["fields"] = {manifest_mappings[k] if k in manifest_mappings else k: v for k, v in snapshot.items()}

            # let's process file_types now!
            data["files"] = dict()
            file_types = data["fields"].pop("file_types")
            for file_type, files in file_types.iteritems():
                if "frame_range" in files:
                    p_file = files["files"][0]["path"]
                    p_file = os.path.join(base_dir, p_file)
                    # let's pick the first file and let the collector run _collect_folder on this
                    # since this is already a file sequence
                    append_path = os.path.dirname(p_file)
                    # list of tag names
                    if append_path not in data["files"]:
                        data["files"][append_path] = list()
                    data["files"][append_path].append(file_type)
                # not a file sequence store the file names, to run _collect_file
                else:
                    p_files = files["files"]
                    for p_file in p_files:
                        append_path = os.path.join(base_dir, p_file["path"])

                        # list of tag names
                        if append_path not in data["files"]:
                            data["files"][append_path] = list()
                        data["files"][append_path].append(file_type)

            processed_snapshots.append({"file": data})

        for note in notes:
            # first replace all the snapshot with the Manifest SG Mappings
            data = dict()
            data["fields"] = {manifest_mappings[k] if k in manifest_mappings else k: v for k, v in note.items()}

            # let's process the attachments now!
            data["files"] = dict()
            attachments = data["fields"].pop("attachments")

            if attachments:
                # add one path of attachment for template parsing
                append_path = os.path.join(base_dir, attachments[0]["path"])

                if append_path not in data["files"]:
                    data["files"][append_path] = list()

            # re-create the attachments field for later use by publish
            data["fields"]["attachments"] = list()

            for attachment in attachments:
                data["fields"]["attachments"].append(os.path.join(base_dir, attachment["path"]))

            processed_snapshots.append({"note": data})

        return processed_snapshots

    def _query_associated_tags(self, tags):
        """
        Queries/Creates tag entities given a list of tag names.

        :param tags: List of tag names.
        :return: List of created/existing tag entities.
        """

        tag_entities = list()

        fields = ["name", "id", "code", "type"]
        for tag_name in tags:
            tag_entity = self.sgtk.shotgun.find_one(entity_type="Tag", filters=[["name", "is", tag_name]], fields=fields)
            if tag_entity:
                tag_entities.append(tag_entity)
            else:
                try:
                    new_entity = self.sgtk.shotgun.create(entity_type="Tag", data=dict(name=tag_name))
                    tag_entities.append(new_entity)
                except Exception:
                    self.logger.error(
                        "Failed to create Tag: %s" % tag_name,
                        extra={
                            "action_show_more_info": {
                                "label": "Show Error log",
                                "tooltip": "Show the error log",
                                "text": traceback.format_exc()
                            }
                        }
                    )
        return tag_entities

    def _collect_manifest_file(self, settings, parent_item, path):
        """
        Process the supplied manifest file.

        :param dict settings: Configured settings for this collector
        :param parent_item: parent item instance
        :param path: Path to analyze

        :returns: The item that was created
        """

        # process the manifest file first, replace the fields to relevant names.
        # collect the tags a file has too.
        processed_entities = self._process_manifest_file(settings, path)

        file_items = list()

        for entity in processed_entities:
            for hook_type, item_data in entity.iteritems():
                files = item_data["files"]
                for p_file, tags in files.iteritems():
                    # fields and items setup
                    fields = item_data["fields"].copy()
                    new_items = list()

                    # file type entity
                    if hook_type == "file":
                        # we need to add tag entities to this field.
                        # let's query/create those first.
                        fields["tags"] = self._query_associated_tags(tags)
                        if os.path.isdir(p_file):
                            items = self._collect_folder(settings, parent_item, p_file)
                            if items:
                                new_items.extend(items)
                        else:
                            item = self._collect_file(settings, parent_item, p_file)
                            if item:
                                new_items.append(item)
                    # note type item
                    elif hook_type == "note":
                        # create a note item
                        item = self._add_note_item(settings, parent_item, attachments=files)
                        if "snapshot_name" in fields:
                            item.description = fields["snapshot_name"]
                        if item:
                            new_items.append(item)

                    # inject the new fields into the item
                    for new_item in new_items:
                        item_fields = new_item.properties["fields"]
                        item_fields.update(fields)

                        if not new_item.description:
                            # adding a default description to item
                            new_item.description = "Created by shotgun_ingest on %s" % str(datetime.date.today())

                        self.logger.info(
                            "Updated fields from snapshot for item: %s" % new_item.name,
                            extra={
                                "action_show_more_info": {
                                    "label": "Show Info",
                                    "tooltip": "Show more info",
                                    "text": "Updated fields:\n%s" %
                                            (pprint.pformat(new_item.properties["fields"]))
                                }
                            }
                        )

                        # we can't let the user change the context of the file being ingested using manifest files
                        new_item.context_change_allowed = False

                    # put the new items back in collector
                    file_items.extend(new_items)

        return file_items

    def _get_item_context_from_path(self, parent_item, properties, path, default_entities=list()):
        """Updates the context of the item from the work_path_template/template, if needed.

        :param properties: properties of the item.
        :param path: path to build the context from, in this class we use os.path.basename of the path.
        """


        sg_filters = [
            ['short_name', 'is', "vendor"]
        ]

        # TODO-- this is not needed right now, since our keys only depend on short_name key of the Step
        # make sure we get the correct Step!
        # if base_context.entity:
        #     # this should handle whether the Step is from Sequence/Shot/Asset
        #     sg_filters.append(["entity_type", "is", base_context.entity["type"]])
        # elif base_context.project:
        #     # this should handle pro
        #     sg_filters.append(["entity_type", "is", base_context.project["type"]])

        fields = ['entity_type', 'code', 'id']

        # add a vendor step to all ingested files
        step_entity = self.sgtk.shotgun.find_one(
            entity_type='Step',
            filters=sg_filters,
            fields=fields
        )

        default_entities = [step_entity]

        work_path_template = self._resolve_work_path_template(properties, path)

        if work_path_template:
            work_tmpl = self.parent.get_template_by_name(work_path_template)
            if work_tmpl and isinstance(work_tmpl, tank.template.TemplateString):
                # use file name if we got TemplateString
                path = os.path.basename(path)

        item_context = super(IngestCollectorPlugin, self)._get_item_context_from_path(parent_item,
                                                                                      properties,
                                                                                      path,
                                                                                      default_entities)

        return item_context

    def _get_template_fields_from_path(self, item, template_name, path):
        """
        Get the fields by parsing the input path using the template derived from
        the input template name.
        """

        work_path_template = item.properties.get("work_path_template")

        if work_path_template:
            work_tmpl = self.parent.get_template_by_name(work_path_template)
            if work_tmpl and isinstance(work_tmpl, tank.template.TemplateString):
                # use file name if the path was parsed using TemplateString
                path = os.path.basename(path)

        fields = super(IngestCollectorPlugin, self)._get_template_fields_from_path(item,
                                                                                   template_name,
                                                                                   path)
        return fields
