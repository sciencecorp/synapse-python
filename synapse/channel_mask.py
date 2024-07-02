kChannelMaskAll = "all"

class ChannelMask(object):
    def __init__(self, mask = kChannelMaskAll):
        pass

    def iter_channels(self):
        for i in range(0, 15):
            yield i
