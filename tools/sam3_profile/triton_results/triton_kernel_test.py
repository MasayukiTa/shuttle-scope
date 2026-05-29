import os, sys
os.environ.setdefault("PYTHONUTF8","1")
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda, "cap", torch.cuda.get_device_capability())
import triton
import triton.language as tl
print("triton", triton.__version__)

@triton.jit
def add_kernel(x_ptr, y_ptr, out_ptr, n, BLOCK: tl.constexpr):
    pid = tl.program_id(0)
    off = pid * BLOCK + tl.arange(0, BLOCK)
    mask = off < n
    x = tl.load(x_ptr + off, mask=mask)
    y = tl.load(y_ptr + off, mask=mask)
    tl.store(out_ptr + off, x + y, mask=mask)

n = 4096
x = torch.rand(n, device="cuda")
y = torch.rand(n, device="cuda")
out = torch.empty_like(x)
grid = (triton.cdiv(n, 1024),)
add_kernel[grid](x, y, out, n, BLOCK=1024)
torch.cuda.synchronize()
err = (out - (x + y)).abs().max().item()
print("KERNEL_MAX_ERR", err)
print("KERNEL_OK" if err < 1e-5 else "KERNEL_FAIL")
