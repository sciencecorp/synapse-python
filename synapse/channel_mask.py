class ChannelMask(object):
    def __init__(self, mask):
        pass

    def iter_channels(self):
        for i in range(0, 511):
            yield i
