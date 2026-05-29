param([string]$plan)
$ErrorActionPreference = "Continue"
$torchlib = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Lib\site-packages\torch\lib"
$env:PATH = "C:\TensorRT\TensorRT-10.16.1.11\lib;C:\TensorRT\TensorRT-10.16.1.11\bin;$torchlib;" + $env:PATH
& "C:\TensorRT\TensorRT-10.16.1.11\bin\trtexec.exe" --loadEngine=$plan --shapes=pixel_values:1x3x518x518 --iterations=50 --warmUp=500 --avgRuns=50 --memPoolSize=workspace:4096 2>&1 | Select-String -Pattern "Latency|Throughput|mean ="
