import maya.cmds as cmds
import sgtk
from sgtk import TankError
from sgtk.templatekey import SequenceKey


HookBaseClass = sgtk.get_hook_baseclass()


class MayaSessionCollector(HookBaseClass):
    """
    Inherits from maya collector.
    Adds maya session based attributes to item.properties.fields
    """
    def _resolve_item_fields(self, settings, item):
        """
        Helper method used to get fields that might not normally be defined in the context.
        Intended to be overridden by DCC-specific subclasses.
        """
        # Now run the parent resolve method
        fields = super(MayaSessionCollector, self)._resolve_item_fields(settings, item)
        publisher = self.parent
        if item.properties.is_sequence:
            first_frame = int(publisher.util.get_frame_number(item.properties.sequence_paths[0]))
            last_frame = int(publisher.util.get_frame_number(item.properties.sequence_paths[-1]))
            # TODO: Update to Dynamic process, When there is a need for different attribute values from the camera.
            focal_length_dict = self.get_focal_length(first_frame, last_frame)
            if focal_length_dict:
                fields.update({"FocalLength": focal_length_dict})
        return fields

    def get_focal_length(self, start_frame, end_frame):
        """
        Returns the Focal length from the scene
        """
        focal_length = {}
        for i in range(start_frame, end_frame + 1):
            act_camera = str(cmds.lookThru(q=1))
            foc_len = round(cmds.getAttr(act_camera + ".focalLength", time=i), 3)
            focal_length[i] = foc_len
        return focal_length

