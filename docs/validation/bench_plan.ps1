$ErrorActionPreference = "Continue"
$torchlib = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Lib\site-packages\torch\lib"
$trt = "C:\TensorRT\TensorRT-10.16.1.11"
$env:PATH = "$trt\lib;$trt\bin;$torchlib;" + $env:PATH
$exe = "$trt\bin\trtexec.exe"
$plan = $args[0]
$extra = $args[1]
Write-Output ("=== BENCH " + $plan + " extra=" + $extra + " ===")
& $exe --loadEngine=$plan --iterations=100 --warmUp=500 --avgRuns=50 $extra 2>&1 | Select-String -Pattern "GPU Compute Time|Throughput|Latency"
