import logging

logging.basicConfig(level=logging.DEBUG)

from synapse.server.entrypoint import main

if __name__ == "__main__":
    main()
