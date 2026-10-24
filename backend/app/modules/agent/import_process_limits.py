"""OS resource bounds for the fixed import parser, not a general command runner."""

import sys
from contextlib import contextmanager

MEMORY_BYTES = 512 * 1024 * 1024
CPU_SECONDS = 45
RESULT_BYTES = 2 * 1024 * 1024


def limit_child():
    if sys.platform == "win32":
        # The parent attaches its Job Object before releasing the stdin startup gate.
        return
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (RESULT_BYTES, RESULT_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


@contextmanager
def contain_process(pid: int):
    if sys.platform != "win32":
        yield
        return
    import ctypes
    from ctypes import wintypes as wt

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wt.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wt.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wt.DWORD),
            ("SchedulingClass", wt.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
    kernel.CreateJobObjectW.restype = wt.HANDLE
    kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    kernel.SetInformationJobObject.restype = wt.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    kernel.AssignProcessToJobObject.restype = wt.BOOL
    kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel.OpenProcess.restype = wt.HANDLE
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    kernel.CloseHandle.restype = wt.BOOL
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise OSError("import process containment unavailable")
    try:
        limits = ExtendedLimits()
        # PROCESS_TIME | ACTIVE_PROCESS | PROCESS_MEMORY | JOB_MEMORY | KILL_ON_JOB_CLOSE.
        limits.BasicLimitInformation.LimitFlags = 0x2 | 0x8 | 0x100 | 0x200 | 0x2000
        limits.BasicLimitInformation.PerProcessUserTimeLimit = CPU_SECONDS * 10_000_000
        # The runner uses the actual interpreter, not a uv/venv launcher.
        limits.BasicLimitInformation.ActiveProcessLimit = 1
        limits.ProcessMemoryLimit = MEMORY_BYTES
        limits.JobMemoryLimit = MEMORY_BYTES
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise OSError("import process containment unavailable")
        handle = kernel.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
        if not handle:
            raise OSError("import process containment unavailable")
        try:
            if not kernel.AssignProcessToJobObject(job, handle):
                raise OSError("import process containment unavailable")
        finally:
            kernel.CloseHandle(handle)
        yield
    finally:
        kernel.CloseHandle(job)
