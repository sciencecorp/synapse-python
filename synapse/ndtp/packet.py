import struct
from enum import Enum
from math import ceil
VERSION = 0x00

class DataType(Enum):
    NBS12 = 0x01
    ST2   = 0x10

def crc16(data: bytes) -> int:
    crc = 0xFFFF  # Initial value
    polynomial = 0x1021  # Polynomial used for CRC16-CCITT

    for byte in data:
        crc ^= (byte << 8)  # XOR byte into the most significant byte of crc

        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ polynomial  # Shift left and XOR with the polynomial
            else:
                crc <<= 1  # Just shift left if no XOR needed

    return crc & 0xFFFF  # Mask to ensure 16-bit value

class Packet():
    def __init__(self, version=VERSION, timestamp=None, seq_num=None, ch_count=None, dtype=None, dtype_custom=None, payload=None, packet_crc16=None):
        self.version = version
        self.timestamp: int = timestamp
        self.seq_num: int = seq_num
        self.ch_count: int = ch_count
        self.dtype: DataType = dtype
        self.dtype_custom = dtype_custom
        self.crc16 = packet_crc16
        if payload is not None:
            self.payload: bytes = payload
        else:
            self.payload = b''

    def to_bytes(self) -> bytes:
        version_dtype = (self.version << 6) | self.dtype.value

        header = struct.pack('>BQBHH', version_dtype, self.timestamp, self.seq_num, self.ch_count, self.dtype_custom)
        return header + self.payload

    def payload_size(self) -> int:
        return len(self.payload)

    def crc_check(self) -> bool:
        return crc16(self.to_bytes()) == self.crc16

    def __str__(self) -> str:
        return f"Packet: version: {self.version}\ntimestamp: {self.timestamp}\nseq_num: {self.seq_num}\nch_count: {self.ch_count}\ndtype: {self.dtype}\ndtype_custom: {self.dtype_custom}\npayload: {self.payload.hex()}\ncrc16: {hex(self.crc16)} (expected {hex(crc16(self.to_bytes()))})"




class NBS12Packet(Packet):
    def __init__(self, version=VERSION, timestamp=None, seq_num=None, ch_count=None, sample_count=None, payload=None):
        super().__init__(version, timestamp, seq_num, ch_count, dtype=DataType.NBS12, dtype_custom=sample_count, payload=payload)
    
    def payload_size(self) -> int: 
        return ceil((self.dtype_custom* 12) / 8) * self.ch_count + 3 * self.ch_count 

    def as_sample_data(self) -> dict[int, list[int]]:
        if len(self.payload) == 0:
            print("No payload")
            return None
        channel_data = {}

        i = 0
        for _ in range(self.ch_count):
            channel_id = int.from_bytes(self.payload[i:i+3])
            # print(f"i: {i} payload: {self.payload[i:i+51].hex()}")
            i += 3
            samples = []
            whole_msb = True
            sample_idx = 0
            while sample_idx < self.dtype_custom:
                # print(f"sample: {sample_idx} payload: {self.payload[i:i+2].hex()}")
                # convert packed 12-bit samples to ints
                if whole_msb:
                    byte_msb = self.payload[i]
                    sample = byte_msb << 4 | self.payload[i+1] >> 4 
                    whole_msb = False 
                else: 
                    byte_msn = self.payload[i] & 0x0F
                    sample = byte_msn << 8 | self.payload[i+1]
                    whole_msb = True
                    i += 1
                i += 1
                sample_idx += 1
                samples.append(sample)

            channel_data[channel_id] = samples

        
        # print(channel_data)
        return channel_data
        

class ST2Packet(Packet):
    def __init__(self, version=VERSION, timestamp=None, seq_num=None, ch_count=None, ch_offset=None, payload=None):
        super().__init__(version, timestamp, seq_num, ch_count, dtype=DataType.ST2, dtype_custom=ch_offset, payload=payload)