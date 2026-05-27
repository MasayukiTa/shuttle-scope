# CMakeLists.txt — person_tracker_native (Phase A1)
#
# 構成:
#   - preprocess  (CUDA)  : preprocess.cu
#   - detector    (C++)   : detector.cpp (ORT GPU 1.24.4)
#   - byte_tracker (C++)  : byte_tracker.cpp (Phase A2, **存在すれば**リンク)
#   - detector_test.exe   : A1 単体テスト
#   - person_tracker_native (pybind11 module) : A3 で bindings.cpp が来たら build
#
# 環境変数:
#   ORT_ROOT        e.g. C:/onnxruntime/onnxruntime-win-x64-gpu-1.24.4
#   CUDA_PATH       (auto from CUDA toolkit install)

cmake_minimum_required(VERSION 3.24)
project(person_tracker_native LANGUAGES CXX CUDA)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CUDA_STANDARD 17)

# --- CUDA ---------------------------------------------------------------
find_package(CUDAToolkit REQUIRED)
# 5060 Ti = sm_120 (Blackwell)。古い toolkit fallback として 89/86 も入れておく。
if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
    set(CMAKE_CUDA_ARCHITECTURES "86;89;120")
endif()

# --- ONNX Runtime (C++ GPU) --------------------------------------------
set(ORT_ROOT "$ENV{ORT_ROOT}" CACHE PATH "ONNX Runtime install root")
if(NOT ORT_ROOT)
    # 既定: 環境整備で配置している場所
    set(ORT_ROOT "C:/onnxruntime/onnxruntime-win-x64-gpu-1.24.4")
endif()

if(NOT EXISTS "${ORT_ROOT}/include/onnxruntime_cxx_api.h")
    message(FATAL_ERROR "ORT_ROOT=${ORT_ROOT} に onnxruntime_cxx_api.h が無い")
endif()

set(ORT_INCLUDE_DIR "${ORT_ROOT}/include")
find_library(ORT_LIBRARY
    NAMES onnxruntime
    PATHS "${ORT_ROOT}/lib"
    NO_DEFAULT_PATH REQUIRED)

# --- Sources ------------------------------------------------------------
set(CORE_SRC
    src/preprocess.cu
    src/detector.cpp
)

# A2 担当 source 群 (byte_tracker / kalman / hungarian) は **あれば**リンク。
# A2 完了前でも A1 のみで build できるよう optional 扱い。
foreach(_a2_src byte_tracker.cpp kalman.cpp hungarian.cpp)
    set(_a2_path "${CMAKE_CURRENT_SOURCE_DIR}/src/${_a2_src}")
    if(EXISTS "${_a2_path}")
        list(APPEND CORE_SRC src/${_a2_src})
        message(STATUS "person_tracker_native: linked A2 source ${_a2_src}")
    else()
        message(STATUS "person_tracker_native: A2 source ${_a2_src} absent (skip)")
    endif()
endforeach()

add_library(person_tracker_core STATIC ${CORE_SRC})
target_include_directories(person_tracker_core PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${ORT_INCLUDE_DIR}
)
target_link_libraries(person_tracker_core PUBLIC
    CUDA::cudart
    "${ORT_LIBRARY}"
)
set_target_properties(person_tracker_core PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    CUDA_SEPARABLE_COMPILATION ON
)

# --- detector_test.exe --------------------------------------------------
add_executable(detector_test src/detector_test.cpp)
target_link_libraries(detector_test PRIVATE person_tracker_core)
target_include_directories(detector_test PRIVATE ${ORT_INCLUDE_DIR})

# DLL を実行 dir に copy (Windows)
if(WIN32)
    set(ORT_DLLS_DIR "${ORT_ROOT}/lib")
    add_custom_command(TARGET detector_test POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E echo "Copying ORT DLLs from ${ORT_DLLS_DIR}"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${ORT_DLLS_DIR}/onnxruntime.dll"
            "$<TARGET_FILE_DIR:detector_test>"
    )
endif()

# --- byte_tracker_test.exe (A2) ----------------------------------------
# A2 単体テスト。golden_byte_tracker.txt を読み込んで Python 版と数値比較。
# byte_tracker.cpp が無い (A2 未配備) なら skip。
set(_bt_test "${CMAKE_CURRENT_SOURCE_DIR}/src/byte_tracker_test.cpp")
if(EXISTS "${_bt_test}" AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/src/byte_tracker.cpp")
    add_executable(byte_tracker_test src/byte_tracker_test.cpp)
    target_link_libraries(byte_tracker_test PRIVATE person_tracker_core)
    message(STATUS "person_tracker_native: byte_tracker_test enabled (A2)")
endif()

# --- pybind11 module (A3) -----------------------------------------------
# bindings.cpp は A3 が書く。存在すれば pyd を build。
set(BIND_SRC "${CMAKE_CURRENT_SOURCE_DIR}/src/bindings.cpp")
if(EXISTS "${BIND_SRC}")
    find_package(pybind11 CONFIG)
    if(pybind11_FOUND)
        pybind11_add_module(person_tracker_native_ext src/bindings.cpp)
        target_link_libraries(person_tracker_native_ext PRIVATE person_tracker_core)
        message(STATUS "person_tracker_native: pybind11 module enabled (A3)")
    else()
        message(WARNING "bindings.cpp あるが pybind11 未検出。skip。")
    endif()
else()
    message(STATUS "person_tracker_native: bindings.cpp absent (A3 pending)")
endif()
