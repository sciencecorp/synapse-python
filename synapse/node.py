class Node(object):
    id = None
    device = None

    def __init__(self):
        pass
    
    @staticmethod
    def from_proto(_):
        raise NotImplementedError

    def to_proto(self):
        pass
