"""有界 PBD 解码器，格式与来源见 文档/PBD格式.md。"""
import hashlib
import struct

_MASK = 0xffffffff
_MAX_NODES = 100_000
_MAX_DEPTH = 64
_MAX_BLOCK = 65_536
_ROUNDS = ((0,4,8,12),(1,5,9,13),(2,6,10,14),(3,7,11,15),
           (0,5,10,15),(1,6,11,12),(2,7,8,13),(3,4,9,14))

def _rotate(value, count):
    return ((value << count) | (value >> (32-count))) & _MASK

def _chacha8(key, counter, low, high):
    initial = list(struct.unpack('<4I', b'expand 32-byte k') + struct.unpack('<8I', key))
    initial += [counter & _MASK, counter >> 32, low, high]
    state = initial.copy()
    for _ in range(4):
        for a,b,c,d in _ROUNDS:
            state[a] = (state[a]+state[b]) & _MASK
            state[d] = _rotate(state[d]^state[a],16)
            state[c] = (state[c]+state[d]) & _MASK
            state[b] = _rotate(state[b]^state[c],12)
            state[a] = (state[a]+state[b]) & _MASK
            state[d] = _rotate(state[d]^state[a],8)
            state[c] = (state[c]+state[d]) & _MASK
            state[b] = _rotate(state[b]^state[c],7)
    return struct.pack('<16I', *((x+y)&_MASK for x,y in zip(state,initial)))

def _empty_xxh32(seed):
    value = (seed+374761393) & _MASK
    value = ((value^(value>>15))*2246822519) & _MASK
    value = ((value^(value>>13))*3266489917) & _MASK
    return value^(value>>16)

def _unmask(payload, seed):
    key = hashlib.blake2s(b'',key=struct.pack('<I',seed)).digest()
    nonce = _empty_xxh32(seed)
    result = bytearray(len(payload))
    for offset in range(0,len(payload),1024):
        words = list(struct.unpack('<16I',_chacha8(key,offset//1024,nonce,seed)))
        for index in range(16,256):
            value = words[index-16]
            value ^= (value<<13)&_MASK
            value ^= value>>17
            value ^= (value<<5)&_MASK
            words.append(value or (seed^nonce) or seed or _MASK)
        stream = struct.pack('<256I',*words)
        for index, byte in enumerate(payload[offset:offset+1024]):
            result[offset+index] = byte^stream[index]
    return bytes(result)

def _inflate(framed, maximum):
    output = bytearray()
    position = 0
    while position < len(framed):
        if len(framed)-position < 2:
            raise ValueError('PBD 压缩帧头不完整')
        size = struct.unpack_from('<H',framed,position)[0]
        position += 2
        if size == 0 or size > len(framed)-position:
            raise ValueError('PBD 压缩帧长度无效')
        block = framed[position:position+size]
        position += size
        cursor = 0
        start = len(output)
        def length(base):
            nonlocal cursor
            value = base
            if base == 15:
                while True:
                    if cursor == len(block):
                        raise ValueError('PBD 压缩长度不完整')
                    extra = block[cursor]
                    cursor += 1
                    value += extra
                    if value > _MAX_BLOCK:
                        raise ValueError('PBD 压缩块过大')
                    if extra != 255:
                        break
            return value
        def allow(amount):
            if len(output)+amount > maximum or len(output)-start+amount > _MAX_BLOCK:
                raise ValueError('PBD 解压数据过大')
        while cursor < len(block):
            token = block[cursor]
            cursor += 1
            literals = length(token>>4)
            if literals > len(block)-cursor:
                raise ValueError('PBD 压缩字面量不完整')
            allow(literals)
            output.extend(block[cursor:cursor+literals])
            cursor += literals
            if cursor == len(block):
                break
            if len(block)-cursor < 2:
                raise ValueError('PBD 压缩引用不完整')
            distance = struct.unpack_from('<H',block,cursor)[0]
            cursor += 2
            if not 0 < distance <= len(output):
                raise ValueError('PBD 压缩引用越界')
            amount = length(token&15)+4
            allow(amount)
            source = len(output)-distance
            pattern = output[source:source+min(distance,amount)]
            output.extend((pattern*((amount+len(pattern)-1)//len(pattern)))[:amount])
        if len(output) == start:
            raise ValueError('PBD 压缩块为空')
    return bytes(output)

class _Values:
    def __init__(self, data, seed):
        self.data = memoryview(data)
        self.cursor = 0
        self.budget = _MAX_NODES
        self.a = (seed&255)^(seed>>24)
        self.b = (seed>>8)&255
        self.c = (seed>>16)&255

    def take(self, size):
        if size > len(self.data)-self.cursor:
            raise ValueError('PBD 数据不完整')
        result = self.data[self.cursor:self.cursor+size]
        self.cursor += size
        return result

    def number(self, fmt):
        return struct.unpack(fmt,self.take(struct.calcsize(fmt)))[0]

    def string(self):
        units = self.number('<I')
        try:
            return bytes(self.take(units*2)).decode('utf-16-le')
        except UnicodeError as exc:
            raise ValueError('PBD 文本编码无效') from exc

    def value(self, depth=0):
        if depth > _MAX_DEPTH or self.budget <= 0:
            raise ValueError('PBD 对象层数或数量过大')
        self.budget -= 1
        tag, check = self.take(2)
        t = (self.a^(self.a<<1))&255
        self.a,self.b,self.c = self.b,self.c,self.c^(self.c>>3)^t^(t>>5)
        if check != self.c:
            raise ValueError('PBD 对象校验不一致')
        if tag == 2:
            return self.string()
        if tag == 4:
            return self.number('<q')
        if tag not in (0x81,0xc1):
            raise ValueError('PBD 对象类型不支持')
        count = self.number('<I')
        minimum = 2 if tag == 0x81 else 6
        if count > self.budget or count > (len(self.data)-self.cursor)//minimum:
            raise ValueError('PBD 对象数量无效')
        if tag == 0x81:
            return [self.value(depth+1) for _ in range(count)]
        result = {}
        for _ in range(count):
            key = self.string()
            if key in result:
                raise ValueError('PBD 对象存在重复字段')
            result[key] = self.value(depth+1)
        return result

def decode_records(raw, maximum):
    if len(raw) < 16 or raw[:8] != b'TJS/4s0\0':
        raise ValueError('PBD 文件头不支持')
    seed,mode,iv_size = struct.unpack_from('<IHH',raw,8)
    if mode != 1 or iv_size != 0:
        raise ValueError('PBD 加密模式不支持')
    reader = _Values(_inflate(_unmask(raw[16:],seed),maximum),seed)
    records = reader.value()
    reader.take(4)  #Observed opaque trailer; its meaning is not established.
    if reader.cursor != len(reader.data):
        raise ValueError('PBD 存在未识别的尾部数据')
    if not isinstance(records,list) or not all(isinstance(item,dict) for item in records):
        raise ValueError('PBD 根对象格式不支持')
    return records
