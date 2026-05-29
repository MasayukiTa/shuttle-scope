$ErrorActionPreference = "Continue"
$torchlib = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Lib\site-packages\torch\lib"
$env:PATH = "C:\TensorRT\TensorRT-10.16.1.11\lib;C:\TensorRT\TensorRT-10.16.1.11\bin;$torchlib;" + $env:PATH
$bench = "C:\Users\kiyus\Desktop\sam3_bench"; $out = "$bench\bf16"
$onnx  = "$bench\sam3_enc_518_fix.onnx"
$plan  = "$out\sam3_enc_linfp16.plan"
if (Test-Path $plan) { Remove-Item $plan }
# fp32 everything EXCEPT all linear projections (qkv, proj, mlp). Attention QK/AV scores + RoPE stay fp32.
$lp = "*:fp32,*/attn/qkv/MatMul:fp16,*/attn/proj/MatMul:fp16,*/mlp/fc1/MatMul:fp16,*/mlp/fc2/MatMul:fp16"
& "C:\TensorRT\TensorRT-10.16.1.11\bin\trtexec.exe" --onnx=$onnx --saveEngine=$plan --fp16 --precisionConstraints=obey --layerPrecisions=$lp --tacticSources=-CUBLAS,-CUBLAS_LT,-CUDNN --memPoolSize=workspace:4096
if (Test-Path $plan) { Write-Output ("PLAN_BUILT_MB " + [math]::Round((Get-Item $plan).Length/1MB,1)) } else { Write-Output "PLAN_MISSING" }
