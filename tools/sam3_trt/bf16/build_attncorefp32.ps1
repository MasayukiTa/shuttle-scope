$ErrorActionPreference = "Continue"
$torchlib = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Lib\site-packages\torch\lib"
$env:PATH = "C:\TensorRT\TensorRT-10.16.1.11\lib;C:\TensorRT\TensorRT-10.16.1.11\bin;$torchlib;" + $env:PATH
$bench = "C:\Users\kiyus\Desktop\sam3_bench"; $out = "$bench\bf16"
$onnx  = "$bench\sam3_enc_518_fix.onnx"
$plan  = "$out\sam3_enc_attncorefp32.plan"
if (Test-Path $plan) { Remove-Item $plan }
# fp16 base; pin ONLY attention score matmuls + softmax + RoPE rotation elementwise + ConvTranspose to fp32.
# qkv/proj/mlp matmuls stay fp16 (proven safe). LayerNorm left fp16 (proven safe in mlpfp16/linfp16).
$lp = "/trunk/blocks.*/attn/MatMul:fp32,/trunk/blocks.*/attn/MatMul_1:fp32,/trunk/blocks.*/attn/Softmax:fp32,/trunk/blocks.*/attn/Mul:fp32,/trunk/blocks.*/attn/Mul_1:fp32,/trunk/blocks.*/attn/Mul_2:fp32,/trunk/blocks.*/attn/Mul_3:fp32,/trunk/blocks.*/attn/Mul_4:fp32,/trunk/blocks.*/attn/Mul_5:fp32,/trunk/blocks.*/attn/Mul_6:fp32,/trunk/blocks.*/attn/Mul_7:fp32,/trunk/blocks.*/attn/Mul_8:fp32,/trunk/blocks.*/attn/Sub:fp32,/trunk/blocks.*/attn/Sub_1:fp32,/trunk/blocks.*/attn/Add:fp32,/trunk/blocks.*/attn/Add_1:fp32,/convs.0/dconv_2x2_0/ConvTranspose:fp32,/convs.0/dconv_2x2_1/ConvTranspose:fp32,/convs.1/dconv_2x2/ConvTranspose:fp32"
& "C:\TensorRT\TensorRT-10.16.1.11\bin\trtexec.exe" --onnx=$onnx --saveEngine=$plan --fp16 --precisionConstraints=obey --layerPrecisions=$lp --tacticSources=-CUBLAS,-CUBLAS_LT,-CUDNN --memPoolSize=workspace:4096
if (Test-Path $plan) { Write-Output ("PLAN_BUILT_MB " + [math]::Round((Get-Item $plan).Length/1MB,1)) } else { Write-Output "PLAN_MISSING" }
