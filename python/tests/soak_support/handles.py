"""Read-only Windows handle census for owned test processes (no handle closing)."""
import ctypes as c
from ctypes import wintypes as w
from collections import Counter


def census(pid):
    class Entry(c.Structure):
        _fields_ = [('object', c.c_void_p), ('pid', c.c_size_t), ('handle', c.c_size_t),
            ('access', w.ULONG), ('backtrace', w.USHORT), ('type', w.USHORT), ('attributes', w.ULONG), ('reserved', w.ULONG)]
    class Unicode(c.Structure):
        _fields_ = [('length', w.USHORT), ('maximum', w.USHORT), ('buffer', c.c_void_p)]
    nt, kernel = c.WinDLL('ntdll'), c.WinDLL('kernel32')
    size = 1024*1024
    while True:
        buf, needed = c.create_string_buffer(size), w.ULONG()
        status = nt.NtQuerySystemInformation(64, buf, size, c.byref(needed))
        if status == 0:
            break
        size = max(size*2, needed.value)
        if size > 128*1024*1024:
            raise RuntimeError(status)
    count = c.c_size_t.from_buffer(buf).value
    entries = (Entry*count).from_buffer(buf, 2*c.sizeof(c.c_size_t))
    kernel.OpenProcess.restype = w.HANDLE
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.DuplicateHandle.argtypes = [w.HANDLE, w.HANDLE, w.HANDLE, c.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD]
    nt.NtQueryObject.argtypes = [w.HANDLE, w.ULONG, c.c_void_p, w.ULONG, c.c_void_p]
    process = kernel.OpenProcess(0x40, False, pid)
    types, counts = {}, Counter()
    try:
        for entry in entries:
            if entry.pid != pid:
                continue
            if entry.type not in types:
                duplicate = w.HANDLE()
                name = f'type-{entry.type}'
                if kernel.DuplicateHandle(process, w.HANDLE(entry.handle), kernel.GetCurrentProcess(), c.byref(duplicate), 0, False, 2):
                    try:
                        info = c.create_string_buffer(4096)
                        if nt.NtQueryObject(duplicate, 2, info, len(info), None) == 0:
                            string = Unicode.from_buffer(info)
                            name = c.wstring_at(string.buffer, string.length//2)
                    finally:
                        kernel.CloseHandle(duplicate)
                types[entry.type] = name
            counts[types[entry.type]] += 1
    finally:
        kernel.CloseHandle(process)
    return dict(counts)


if __name__ == '__main__':
    import json, sys
    print(json.dumps(census(int(sys.argv[1]))))
