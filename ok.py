#!/usr/bin/env python3
"""
Python wrapper for Opal Kelly FrontPanel library using ctypes.
This module provides a Python interface to the libokFrontPanel.dylib library.
"""

import ctypes
import os
from pathlib import Path

# Load the library
LIB_PATH = Path(__file__).parent / "libokFrontPanel.dylib"
if not LIB_PATH.exists():
    raise FileNotFoundError(f"libokFrontPanel.dylib not found at {LIB_PATH}")

_lib = ctypes.CDLL(str(LIB_PATH))

# Error codes
class ErrorCode:
    NoError = 0
    Failed = -1
    Timeout = -2
    DoneNotHigh = -3
    TransferError = -4
    CommunicationError = -5
    InvalidBitstream = -6
    FileError = -7
    DeviceNotOpen = -8
    InvalidEndpoint = -9
    InvalidBlockSize = -10
    I2CRestrictedAddress = -11
    I2CBitError = -12
    I2CNack = -13
    I2CUnknownStatus = -14
    UnsupportedFeature = -15
    FIFOUnderflow = -16
    FIFOOverflow = -17
    DataAlignmentError = -18
    InvalidResetProfile = -19
    InvalidParameter = -20

# Define function signatures
_lib.okFrontPanel_Construct.argtypes = []
_lib.okFrontPanel_Construct.restype = ctypes.c_void_p

_lib.okFrontPanel_Destruct.argtypes = [ctypes.c_void_p]
_lib.okFrontPanel_Destruct.restype = None

_lib.okFrontPanel_GetDeviceCount.argtypes = [ctypes.c_void_p]
_lib.okFrontPanel_GetDeviceCount.restype = ctypes.c_int

_lib.okFrontPanel_GetDeviceListSerial.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
_lib.okFrontPanel_GetDeviceListSerial.restype = None

_lib.okFrontPanel_OpenBySerial.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
_lib.okFrontPanel_OpenBySerial.restype = ctypes.c_int

_lib.okFrontPanel_ConfigureFPGA.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
_lib.okFrontPanel_ConfigureFPGA.restype = ctypes.c_int

_lib.okFrontPanel_SetWireInValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong]
_lib.okFrontPanel_SetWireInValue.restype = ctypes.c_int

_lib.okFrontPanel_UpdateWireIns.argtypes = [ctypes.c_void_p]
_lib.okFrontPanel_UpdateWireIns.restype = ctypes.c_int

_lib.okFrontPanel_UpdateWireOuts.argtypes = [ctypes.c_void_p]
_lib.okFrontPanel_UpdateWireOuts.restype = ctypes.c_int

_lib.okFrontPanel_GetWireOutValue.argtypes = [ctypes.c_void_p, ctypes.c_int]
_lib.okFrontPanel_GetWireOutValue.restype = ctypes.c_ulong

_lib.okFrontPanel_WriteToPipeIn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long, ctypes.POINTER(ctypes.c_ubyte)]
_lib.okFrontPanel_WriteToPipeIn.restype = ctypes.c_long

_lib.okFrontPanel_ReadFromPipeOut.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long, ctypes.POINTER(ctypes.c_ubyte)]
_lib.okFrontPanel_ReadFromPipeOut.restype = ctypes.c_long

# Note: Some functions may not be available in C API, handle gracefully
def _safe_getattr(lib, name, default=None):
    """Safely get attribute from library, return default if not found"""
    try:
        return getattr(lib, name)
    except AttributeError:
        return default

# Try to get optional functions (may not exist in C API)
_okFrontPanel_IsOpen = _safe_getattr(_lib, 'okFrontPanel_IsOpen')
if _okFrontPanel_IsOpen:
    _okFrontPanel_IsOpen.argtypes = [ctypes.c_void_p]
    _okFrontPanel_IsOpen.restype = ctypes.c_int

# GetErrorString has different signature in C API
_okFrontPanel_GetErrorString = _safe_getattr(_lib, 'okFrontPanel_GetErrorString')
if _okFrontPanel_GetErrorString:
    # C API: okFrontPanel_GetErrorString(int ec, char* buf, int length)
    _okFrontPanel_GetErrorString.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    _okFrontPanel_GetErrorString.restype = None


class okCFrontPanel:
    """Python wrapper for okCFrontPanel C++ class"""
    
    NoError = ErrorCode.NoError
    
    def __init__(self):
        self.handle = _lib.okFrontPanel_Construct()
        if not self.handle:
            raise RuntimeError("Failed to construct okCFrontPanel")
    
    def __del__(self):
        if hasattr(self, 'handle') and self.handle:
            _lib.okFrontPanel_Destruct(self.handle)
    
    def GetDeviceCount(self):
        """Get the number of connected Opal Kelly devices"""
        return _lib.okFrontPanel_GetDeviceCount(self.handle)
    
    def GetDeviceListSerial(self, num):
        """Get the serial number of device at index num"""
        buf = ctypes.create_string_buffer(11)  # OK_MAX_SERIALNUMBER_LENGTH = 11
        _lib.okFrontPanel_GetDeviceListSerial(self.handle, num, buf, 11)
        return buf.value.decode('utf-8')
    
    def OpenBySerial(self, serial):
        """Open device by serial number"""
        if isinstance(serial, str):
            serial = serial.encode('utf-8')
        return _lib.okFrontPanel_OpenBySerial(self.handle, serial)
    
    def IsOpen(self):
        """Check if device is open"""
        if _okFrontPanel_IsOpen:
            return bool(_okFrontPanel_IsOpen(self.handle))
        # Fallback: assume open if handle exists (not perfect but works)
        return self.handle is not None
    
    def ConfigureFPGA(self, bitfile):
        """Configure FPGA with bitfile"""
        if isinstance(bitfile, str):
            bitfile = bitfile.encode('utf-8')
        return _lib.okFrontPanel_ConfigureFPGA(self.handle, bitfile)
    
    def SetWireInValue(self, ep, val, mask=0xFFFFFFFF):
        """Set WireIn value"""
        return _lib.okFrontPanel_SetWireInValue(self.handle, ep, val & 0xFFFFFFFF, mask & 0xFFFFFFFF)
    
    def UpdateWireIns(self):
        """Update WireIns"""
        return _lib.okFrontPanel_UpdateWireIns(self.handle)
    
    def UpdateWireOuts(self):
        """Update WireOuts"""
        return _lib.okFrontPanel_UpdateWireOuts(self.handle)
    
    def GetWireOutValue(self, ep):
        """Get WireOut value"""
        return _lib.okFrontPanel_GetWireOutValue(self.handle, ep)
    
    def WriteToPipeIn(self, ep, data):
        """Write data to PipeIn"""
        if isinstance(data, (bytes, bytearray)):
            data_array = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        else:
            raise TypeError("data must be bytes or bytearray")
        length = len(data)
        result = _lib.okFrontPanel_WriteToPipeIn(self.handle, ep, length, data_array)
        return result
    
    def ReadFromPipeOut(self, ep, length):
        """Read data from PipeOut"""
        data_array = (ctypes.c_ubyte * length)()
        result = _lib.okFrontPanel_ReadFromPipeOut(self.handle, ep, length, data_array)
        if result < 0:
            return bytearray()
        return bytearray(data_array[:result])
    
    def GetLastError(self):
        """Get last error code (may not be available in C API)"""
        # C API doesn't have GetLastError, return 0 (NoError) as default
        return ErrorCode.NoError
    
    @staticmethod
    def GetErrorString(error_code):
        """Get error string for error code"""
        if _okFrontPanel_GetErrorString:
            buf = ctypes.create_string_buffer(256)
            _okFrontPanel_GetErrorString(error_code, buf, 256)
            return buf.value.decode('utf-8', errors='ignore')
        # Fallback error messages
        error_messages = {
            ErrorCode.NoError: "No error",
            ErrorCode.Failed: "Operation failed",
            ErrorCode.Timeout: "Timeout",
            ErrorCode.DeviceNotOpen: "Device not open",
            ErrorCode.InvalidEndpoint: "Invalid endpoint",
            ErrorCode.CommunicationError: "Communication error",
        }
        return error_messages.get(error_code, f"Unknown error {error_code}")
