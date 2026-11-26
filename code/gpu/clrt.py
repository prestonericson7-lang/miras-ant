"""clrt.py -- a small OpenCL runtime over the Windows ICD loader (OpenCL.dll) with ctypes only: no package, no download.
Picks the device whose name contains a given word (the B70 is 'Arc'), builds a program from source, runs kernels on numpy arrays.
Written for the prize line's GPU twin (11-13-2026). Nothing here computes a result; the kernels do."""
import ctypes as C
import numpy as np

cl = C.WinDLL("OpenCL.dll")
vp, sz, u32, u64, i32 = C.c_void_p, C.c_size_t, C.c_uint, C.c_uint64, C.c_int
cl.clGetPlatformIDs.argtypes = [u32, C.POINTER(vp), C.POINTER(u32)]
cl.clGetDeviceIDs.argtypes = [vp, u64, u32, C.POINTER(vp), C.POINTER(u32)]
cl.clGetDeviceInfo.argtypes = [vp, u32, sz, vp, C.POINTER(sz)]
cl.clCreateContext.argtypes = [vp, u32, C.POINTER(vp), vp, vp, C.POINTER(i32)]; cl.clCreateContext.restype = vp
cl.clCreateCommandQueueWithProperties.argtypes = [vp, vp, vp, C.POINTER(i32)]; cl.clCreateCommandQueueWithProperties.restype = vp
cl.clCreateProgramWithSource.argtypes = [vp, u32, C.POINTER(C.c_char_p), C.POINTER(sz), C.POINTER(i32)]; cl.clCreateProgramWithSource.restype = vp
cl.clBuildProgram.argtypes = [vp, u32, C.POINTER(vp), C.c_char_p, vp, vp]
cl.clGetProgramBuildInfo.argtypes = [vp, vp, u32, sz, vp, C.POINTER(sz)]
cl.clCreateKernel.argtypes = [vp, C.c_char_p, C.POINTER(i32)]; cl.clCreateKernel.restype = vp
cl.clCreateBuffer.argtypes = [vp, u64, sz, vp, C.POINTER(i32)]; cl.clCreateBuffer.restype = vp
cl.clSetKernelArg.argtypes = [vp, u32, sz, vp]
cl.clEnqueueNDRangeKernel.argtypes = [vp, vp, u32, C.POINTER(sz), C.POINTER(sz), C.POINTER(sz), u32, vp, vp]
cl.clEnqueueReadBuffer.argtypes = [vp, vp, u32, sz, sz, vp, u32, vp, vp]
cl.clEnqueueWriteBuffer.argtypes = [vp, vp, u32, sz, sz, vp, u32, vp, vp]
cl.clFinish.argtypes = [vp]
cl.clReleaseMemObject.argtypes = [vp]
CL_DEVICE_TYPE_ALL = 0xFFFFFFFF; CL_DEVICE_NAME = 0x102B; CL_PROGRAM_BUILD_LOG = 0x1183
CL_MEM_READ_WRITE, CL_MEM_READ_ONLY, CL_MEM_WRITE_ONLY, CL_MEM_COPY_HOST_PTR = 1, 4, 2, 32


class CLError(RuntimeError):
    pass


def chk(err, what):
    if err:
        raise CLError(f"{what}: OpenCL error {err}")


class Device:
    def __init__(self, name_word="Arc"):
        n = u32(); chk(cl.clGetPlatformIDs(0, None, C.byref(n)), "platforms"); plats = (vp * max(1, n.value))(); cl.clGetPlatformIDs(n.value, plats, None)
        self.dev = None; self.name = ""
        for i in range(n.value):
            nd = u32()
            if cl.clGetDeviceIDs(plats[i], CL_DEVICE_TYPE_ALL, 0, None, C.byref(nd)) or nd.value == 0:
                continue
            devs = (vp * nd.value)(); cl.clGetDeviceIDs(plats[i], CL_DEVICE_TYPE_ALL, nd.value, devs, None)
            for j in range(nd.value):
                k = sz(); cl.clGetDeviceInfo(devs[j], CL_DEVICE_NAME, 0, None, C.byref(k)); b = C.create_string_buffer(k.value); cl.clGetDeviceInfo(devs[j], CL_DEVICE_NAME, k, b, None)
                nm = b.value.decode(errors="replace")
                if name_word.lower() in nm.lower() and self.dev is None:
                    self.dev = devs[j]; self.name = nm; self.plat = plats[i]
        if self.dev is None:
            raise CLError(f"no OpenCL device named like '{name_word}'")
        err = i32(); d = vp(self.dev)
        self.ctx = cl.clCreateContext(None, 1, C.byref(d), None, None, C.byref(err)); chk(err.value, "context")
        self.q = cl.clCreateCommandQueueWithProperties(self.ctx, self.dev, None, C.byref(err)); chk(err.value, "queue")

    def program(self, source, options=""):
        src = C.c_char_p(source.encode()); ln = sz(len(source)); err = i32()
        prog = cl.clCreateProgramWithSource(self.ctx, 1, C.byref(src), C.byref(ln), C.byref(err)); chk(err.value, "program")
        d = vp(self.dev); e = cl.clBuildProgram(prog, 1, C.byref(d), options.encode(), None, None)
        k = sz(); cl.clGetProgramBuildInfo(prog, self.dev, CL_PROGRAM_BUILD_LOG, 0, None, C.byref(k)); b = C.create_string_buffer(k.value)
        cl.clGetProgramBuildInfo(prog, self.dev, CL_PROGRAM_BUILD_LOG, k, b, None); self.build_log = b.value.decode(errors="replace")
        if e:
            raise CLError("build failed:\n" + self.build_log)
        return prog

    def kernel(self, prog, name):
        err = i32(); k = cl.clCreateKernel(prog, name.encode(), C.byref(err)); chk(err.value, "kernel " + name); return k

    def buf_in(self, arr):
        arr = np.ascontiguousarray(arr); err = i32()
        b = cl.clCreateBuffer(self.ctx, CL_MEM_READ_ONLY | CL_MEM_COPY_HOST_PTR, arr.nbytes, arr.ctypes.data_as(vp), C.byref(err)); chk(err.value, "buffer in"); return b

    def buf_out(self, nbytes):
        err = i32(); b = cl.clCreateBuffer(self.ctx, CL_MEM_READ_WRITE, max(1, nbytes), None, C.byref(err)); chk(err.value, "buffer out"); return b

    def write(self, b, arr):
        arr = np.ascontiguousarray(arr); chk(cl.clEnqueueWriteBuffer(self.q, b, 1, 0, arr.nbytes, arr.ctypes.data_as(vp), 0, None, None), "write")

    def read(self, b, arr):
        chk(cl.clEnqueueReadBuffer(self.q, b, 1, 0, arr.nbytes, arr.ctypes.data_as(vp), 0, None, None), "read"); return arr

    def release(self, b):
        cl.clReleaseMemObject(b)

    def run(self, kern, global_size, args, local_size=None):
        """args: a list of (ctype value) or buffer handles (c_void_p); each set in order."""
        for i, a in enumerate(args):
            if isinstance(a, int):            # a buffer handle (cl_mem) passed as a plain int
                h = vp(a); chk(cl.clSetKernelArg(kern, i, C.sizeof(h), C.byref(h)), f"arg {i}")
            else:
                chk(cl.clSetKernelArg(kern, i, C.sizeof(a), C.byref(a)), f"arg {i}")
        g = sz(int(global_size)); l = sz(int(local_size)) if local_size else None
        chk(cl.clEnqueueNDRangeKernel(self.q, kern, 1, None, C.byref(g), C.byref(l) if l else None, 0, None, None), "enqueue")

    def finish(self):
        chk(cl.clFinish(self.q), "finish")
