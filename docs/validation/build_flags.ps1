$ErrorActionPreference = "Continue"
$torchlib = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Lib\site-packages\torch\lib"
$trt = "C:\TensorRT\TensorRT-10.16.1.11"
$env:PATH = "$trt\lib;$trt\bin;$torchlib;" + $env:PATH
$bench = "C:\Users\kiyus\Desktop\sam3_bench"
$flags = "$bench\flags"
$onnx = "$bench\sam3_enc_518_fix.onnx"
$exe = "$trt\bin\trtexec.exe"
$nt = "--tacticSources=-CUBLAS,-CUBLAS_LT,-CUDNN"

# opt level 5
$p1 = "$flags\sam3_enc_opt5.plan"
Write-Output "=== BUILD opt5 ==="
& $exe --onnx=$onnx --saveEngine=$p1 --noTF32 $nt --builderOptimizationLevel=5 --memPoolSize=workspace:4096 2>&1 | Select-Object -Last 6
if (Test-Path $p1) { Write-Output ("opt5_MB " + [math]::Round((Get-Item $p1).Length/1MB,1)) } else { Write-Output "opt5_MISSING" }

# large mempool
$p2 = "$flags\sam3_enc_mempool8g.plan"
Write-Output "=== BUILD mempool8g ==="
& $exe --onnx=$onnx --saveEngine=$p2 --noTF32 $nt --memPoolSize=workspace:8192 2>&1 | Select-Object -Last 6
if (Test-Path $p2) { Write-Output ("mempool8g_MB " + [math]::Round((Get-Item $p2).Length/1MB,1)) } else { Write-Output "mempool8g_MISSING" }
Write-Output "ALLDONE"
