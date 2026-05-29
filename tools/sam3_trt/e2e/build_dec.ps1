$ErrorActionPreference = "Continue"
$torchlib = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Lib\site-packages\torch\lib"
$env:PATH = "C:\TensorRT\TensorRT-10.16.1.11\lib;C:\TensorRT\TensorRT-10.16.1.11\bin;$torchlib;" + $env:PATH
$e2e = "C:\Users\kiyus\Desktop\sam3_bench\e2e"
$onnx = "$e2e\sam3_dec.onnx"
$plan = "$e2e\sam3_dec_notactic.plan"
& "C:\TensorRT\TensorRT-10.16.1.11\bin\trtexec.exe" --onnx=$onnx --saveEngine=$plan --noTF32 --tacticSources=-CUBLAS,-CUBLAS_LT,-CUDNN --memPoolSize=workspace:4096 2>&1 | Select-Object -Last 25
if (Test-Path $plan) { Write-Output ("PLAN_BUILT_MB " + [math]::Round((Get-Item $plan).Length/1MB,1)) } else { Write-Output "PLAN_MISSING" }
