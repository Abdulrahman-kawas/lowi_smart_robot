cmake_minimum_required(VERSION 3.16)
project(spider_lidar_bridge CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Path to a clone of https://github.com/unitreerobotics/unilidar_sdk2
set(UNILIDAR_SDK_DIR "$ENV{HOME}/unilidar_sdk2/unitree_lidar_sdk" CACHE PATH "unitree_lidar_sdk folder")
if(NOT EXISTS "${UNILIDAR_SDK_DIR}/include/unitree_lidar_sdk.h")
  message(FATAL_ERROR "unilidar SDK not found in ${UNILIDAR_SDK_DIR}; pass -DUNILIDAR_SDK_DIR=...")
endif()

find_package(PkgConfig REQUIRED)
pkg_check_modules(ZMQ REQUIRED libzmq)
find_package(Threads REQUIRED)

add_executable(lidar_bridge lidar_bridge.cpp)
target_include_directories(lidar_bridge PRIVATE ${UNILIDAR_SDK_DIR}/include ${ZMQ_INCLUDE_DIRS})
target_link_libraries(lidar_bridge PRIVATE
  ${UNILIDAR_SDK_DIR}/lib/${CMAKE_SYSTEM_PROCESSOR}/libunilidar_sdk2.a
  ${ZMQ_LIBRARIES}
  Threads::Threads)
target_compile_options(lidar_bridge PRIVATE -O2 -Wall -Wextra)
