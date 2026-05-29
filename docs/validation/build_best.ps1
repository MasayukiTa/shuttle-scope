$ErrorActionPreference = "Continue"
$torchlib = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Lib\site-packages\torch\lib"
$trt = "C:\TensorRT\TensorRT-10.16.1.11"
$env:PATH = "$trt\lib;$trt\bin;$torchlib;" + $env:PATH
$bench = "C:\Users\kiyus\Desktop\sam3_bench"
$flags = "$bench\flags"
$onnx = "$bench\sam3_enc_518_fix.onnx"
$exe = "$trt\bin\trtexec.exe"
$nt = "--tacticSources=-CUBLAS,-CUBLAS_LT,-CUDNN"
$p = "$flags\sam3_enc_best.plan"
Write-Output "=== BUILD best ==="
& $exe --onnx=$onnx --saveEngine=$p --best $nt --memPoolSize=workspace:4096 2>&1 | Select-Object -Last 8
if (Test-Path $p) { Write-Output ("best_MB " + [math]::Round((Get-Item $p).Length/1MB,1)) } else { Write-Output "best_MISSING" }
Write-Output "ALLDONE"
