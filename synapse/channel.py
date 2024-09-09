from synapse.api.channel_pb2 import Channel as PBChannel


class Channel(object):
    def __init__(self, channel_id, electrode_id=None, reference_id=None):
        self.channel_id = channel_id

        self.electrode_id = electrode_id
        self.reference_id = reference_id

    @staticmethod
    def from_proto(proto: PBChannel):
        return Channel(proto.id, proto.electrode_id, proto.reference_id)

    def to_proto(self):
        return PBChannel(
            id=self.channel_id,
            electrode_id=self.electrode_id,
            reference_id=self.reference_id,
        )
