FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libc++1 \
    libatomic1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "numpy<2" \
    "onnx==1.16.2" \
    pyyaml \
    packaging \
    "protobuf>=3.20,<5"

COPY convert.py /opt/model-converter/convert.py

ENTRYPOINT ["python3", "/opt/model-converter/convert.py"]
