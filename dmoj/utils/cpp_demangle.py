from ctypes import CDLL, POINTER, byref, c_char_p, c_int, c_size_t, c_void_p, string_at
from ctypes.util import find_library
from typing import Any
import platform

__all__ = ['demangle']

# Chọn thư viện C dựa trên hệ điều hành
if platform.system() == 'Windows':
    libc = CDLL('msvcrt.dll')
    # Trên Windows với MSVC, không có __cxa_demangle mặc định
    try:
        from ctypes import windll
        dbghelp = windll.dbghelp
        dbghelp.UnDecorateSymbolName.argtypes = [c_char_p, c_char_p, c_int, c_int]
        dbghelp.UnDecorateSymbolName.restype = c_int
        def demangle(name: bytes) -> bytes:
            output = (c_char_p * 1024)()
            length = dbghelp.UnDecorateSymbolName(name, output, 1024, 0)
            return output.value if length else name
    except AttributeError:
        # Nếu không có DbgHelp, trả về tên gốc
        def demangle(name: bytes) -> bytes:
            return name
else:
    libc_name = find_library('c') or 'libc.so.6'
    libc = CDLL(libc_name)

    libstdcxx_path = find_library('stdc++') or 'libstdc++.so.6'
    libcxx_path = find_library('c++') or 'libc++.so'

    libstdcxx: Any = None if libstdcxx_path is None else CDLL(libstdcxx_path)
    libcxx: Any = None if libcxx_path is None else CDLL(libcxx_path)

    try:
        __cxa_demangle = libstdcxx.__cxa_demangle
    except AttributeError:
        __cxa_demangle = libcxx.__cxa_demangle

    __cxa_demangle.argtypes = [c_char_p, c_char_p, POINTER(c_size_t), POINTER(c_int)]
    __cxa_demangle.restype = c_void_p

    free = libc.free
    free.argtypes = [c_void_p]
    free.restype = None

    def demangle(name: bytes) -> bytes:
        status = c_int()
        result = __cxa_demangle(name, None, None, byref(status))

        if result:
            value = string_at(result)
            free(result)
            return value

        if status.value == -1:
            raise MemoryError()
        elif status.value == -2:
            return name
        elif status.value == -3:
            raise RuntimeError('__cxa_demangle reported invalid argument')
        else:
            raise RuntimeError(f'unknown return value {status.value} from __cxa_demangle')