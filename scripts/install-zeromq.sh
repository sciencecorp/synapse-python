# Build ZMQ from source
#  enable draft APIs (RADIO/DISH)
#  https://github.com/zeromq/pyzmq/blob/71868834f72c44606bb48beb2d3da181c79afa1f/docs/source/howto/draft.md

ZMQ_VERSION=${ZMQ_VERSION:-4.3.5}
ZMQ_PREFIX=${ZMQ_PREFIX:-$(pwd)/external/zmq}
TMP_DIR=${pwd}/tmp
CPU_COUNT=${CPU_COUNT:-$(python3 -c "import os; print(os.cpu_count())")}

echo "Building zeromq v$ZMQ_VERSION from source in \"$ZMQ_PREFIX\""
mkdir -p $ZMQ_PREFIX
if [ -f $ZMQ_PREFIX/lib/libzmq.a ]; then
  echo " - zeromq v$ZMQ_VERSION already installed in \"$ZMQ_PREFIX\""
  exit 0
fi

mkdir -p $TMP_DIR
cd $TMP_DIR
if [ ! -f libzmq.tar.gz ]; then
  echo " - downloading zeromq v$ZMQ_VERSION"
  wget https://github.com/zeromq/libzmq/releases/download/v${ZMQ_VERSION}/zeromq-${ZMQ_VERSION}.tar.gz -O libzmq.tar.gz
fi

tar -xzf libzmq.tar.gz
cd zeromq-${ZMQ_VERSION}
./configure --prefix=$ZMQ_PREFIX --enable-drafts
make -j$CPU_COUNT && make install

echo " - zeromq v$ZMQ_VERSION installed in \"$ZMQ_PREFIX\""
