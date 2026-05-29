$ErrorActionPreference = "Continue"
$torchlib = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Lib\site-packages\torch\lib"
$env:PATH = "C:\TensorRT\TensorRT-10.16.1.11\lib;C:\TensorRT\TensorRT-10.16.1.11\bin;$torchlib;" + $env:PATH
$bench = "C:\Users\kiyus\Desktop\sam3_bench"
$out   = "$bench\bf16"
$onnx  = "$bench\sam3_enc_518_fix.onnx"
$plan  = "$out\sam3_enc_fp16_mix.plan"
if (Test-Path $plan) { Remove-Item $plan }
# Pin sensitive ops to fp32: all LayerNorm, all Softmax, the 3 ConvTranspose.
$lp = "*norm*/LayerNormalization:fp32,*ln_pre*:fp32,*/attn/Softmax:fp32,/convs.0/dconv_2x2_0/ConvTranspose:fp32,/convs.0/dconv_2x2_1/ConvTranspose:fp32,/convs.1/dconv_2x2/ConvTranspose:fp32"
& "C:\TensorRT\TensorRT-10.16.1.11\bin\trtexec.exe" --onnx=$onnx --saveEngine=$plan --fp16 --precisionConstraints=obey --layerPrecisions=$lp --tacticSources=-CUBLAS,-CUBLAS_LT,-CUDNN --memPoolSize=workspace:4096
if (Test-Path $plan) { Write-Output ("PLAN_BUILT_MB " + [math]::Round((Get-Item $plan).Length/1MB,1)) } else { Write-Output "PLAN_MISSING" }
