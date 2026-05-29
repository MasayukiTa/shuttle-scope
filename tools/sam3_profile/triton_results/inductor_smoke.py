import os
os.environ.setdefault("PYTHONUTF8","1")
import torch, time
print("torch", torch.__version__)

class M(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.l1 = torch.nn.Linear(512, 512)
        self.l2 = torch.nn.Linear(512, 512)
    def forward(self, x):
        x = torch.relu(self.l1(x))
        x = torch.sigmoid(self.l2(x))
        return x * 2.0 + 1.0

m = M().cuda().eval()
x = torch.randn(64, 512, device="cuda")
with torch.no_grad():
    ref = m(x)
    try:
        cm = torch.compile(m, mode="max-autotune")
        for _ in range(3):
            out = cm(x); torch.cuda.synchronize()
        err = (out - ref).abs().max().item()
        print("INDUCTOR_COMPILE_OK max_err", err)
    except Exception as e:
        import traceback
        print("INDUCTOR_FAIL")
        print(traceback.format_exc()[-2000:])
