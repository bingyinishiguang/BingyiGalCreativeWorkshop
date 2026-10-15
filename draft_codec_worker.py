"""Isolated adapter for the tested Jianying 7.2 Windows draft codec ABI."""
import ctypes as C
import os
import sys
from pathlib import Path


def main(args=None):
    operation, install, source, target = sys.argv[1:] if args is None else args
    if operation not in ('dec', 'enc'):
        raise ValueError('不支持的草稿编解码操作')
    install, source, target = map(lambda p: Path(p).resolve(), (install, source, target))
    if sys.platform != 'win32' or not (install/'videoeditor.dll').is_file():
        raise ValueError('需要支持的 Windows 剪映安装目录')
    os.environ['PATH'] = str(install)+os.pathsep+os.environ.get('PATH','')
    os.chdir(install)
    handle = os.add_dll_directory(str(install))
    dll = C.CDLL(str(install/'videoeditor.dll'))
    class Data(C.Union):
        _fields_=[('small',C.c_char*16),('ptr',C.c_void_p)]
    class Str(C.Structure):
        _fields_=[('data',Data),('size',C.c_ulonglong),('capacity',C.c_ulonglong)]
    def arg(b):
        s=Str();s.size=len(b);s.capacity=15;keep=None
        if len(b)<16:s.data.small=b
        else:keep=C.create_string_buffer(b);s.data.ptr=C.cast(keep,C.c_void_p);s.capacity=len(b)
        return s,keep
    def take(s):
        if s.size>50_000_000:raise ValueError('返回草稿过大')
        return C.string_at(C.addressof(s) if s.capacity<16 else s.data.ptr,s.size)
    dec=getattr(dll,'?decrypt@EncryptUtils@lvve@@QEAA?AV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV34@0AEA_N@Z')
    dec.argtypes=[C.c_void_p,C.POINTER(Str),C.POINTER(Str),C.POINTER(Str),C.POINTER(C.c_bool)];dec.restype=C.c_void_p
    enc=getattr(dll,'?encrypt@EncryptUtils@lvve@@QEAA?AV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV34@@Z')
    enc.argtypes=[C.c_void_p,C.POINTER(Str),C.POINTER(Str)];enc.restype=C.c_void_p
    enable=getattr(dll,'?enable@EncryptUtils@lvve@@QEAAX_N@Z');enable.argtypes=[C.c_void_p,C.c_bool]
    def decrypt(b):
        s,k=arg(b);p,kp=arg(b'{}');out=Str();out.capacity=15;ok=C.c_bool(False)
        dec(None,C.byref(out),C.byref(s),C.byref(p),C.byref(ok))
        if not ok.value:raise ValueError('解密失败')
        return take(out)
    b=source.read_bytes()
    if operation=='dec':result=decrypt(b)
    elif operation=='enc':
        enable(None,True);s,k=arg(b);out=Str();out.capacity=15;enc(None,C.byref(out),C.byref(s));result=take(out)
        if decrypt(result)!=b:raise ValueError('加密往返校验失败')
    else:raise ValueError('未知操作')
    target.write_bytes(result)


if __name__=='__main__':main()
