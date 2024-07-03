CHANNEL_MASK_ALL = "all"

class ChannelMask(object):
    def __init__(self, mask = CHANNEL_MASK_ALL):
        pass

    def iter_channels(self):
        for i in range(0, 15):
            yield i
