$ErrorActionPreference = "Continue"
$torchlib = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Lib\site-packages\torch\lib"
$trt = "C:\TensorRT\TensorRT-10.16.1.11"
$env:PATH = "$trt\lib;$trt\bin;$torchlib;" + $env:PATH
$bench = "C:\Users\kiyus\Desktop\sam3_bench"
$flags = "$bench\flags"
$onnx = "$bench\sam3_enc_518_fix.onnx"
$plan = "$flags\sam3_enc_fp8.plan"
& "$trt\bin\trtexec.exe" --onnx=$onnx --saveEngine=$plan --fp8 --noTF32 --tacticSources=-CUBLAS,-CUBLAS_LT,-CUDNN --memPoolSize=workspace:4096 2>&1 | Select-Object -Last 30
if (Test-Path $plan) { Write-Output ("PLAN_BUILT_MB " + [math]::Round((Get-Item $plan).Length/1MB,1)) } else { Write-Output "PLAN_MISSING" }
