// lidar_bridge: Unitree L2 (unilidar_sdk2, Ethernet/UDP) -> ZeroMQ PUB for the Python body.
//
// Messages (multipart):
//   ["cloud", struct{double stamp; uint32 id; uint32 n;}, float32[n*4] x,y,z,intensity]
//   ["imu",   double stamp,                              float32[10] quat xyzw, gyro xyz, acc xyz]
//
// Configuration via environment variables (defaults match the L2 factory settings):
//   LIDAR_IP=192.168.1.62 LIDAR_PORT=6101 LOCAL_IP=192.168.1.2 LOCAL_PORT=6201
//   ZMQ_ENDPOINT=ipc:///tmp/spider_lidar.ipc POINT_STRIDE=2 RANGE_MIN=0.05 RANGE_MAX=12

#include <zmq.h>

#include <algorithm>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include <unistd.h>

#include "unitree_lidar_sdk.h"

using namespace unilidar_sdk2;

namespace {

volatile std::sig_atomic_t g_stop = 0;
void on_signal(int) { g_stop = 1; }

std::string env_or(const char* key, const char* fallback) {
  const char* v = std::getenv(key);
  return (v != nullptr && *v != '\0') ? std::string(v) : std::string(fallback);
}

#pragma pack(push, 1)
struct CloudHeader {
  double stamp;
  uint32_t id;
  uint32_t n;
};
#pragma pack(pop)
static_assert(sizeof(CloudHeader) == 16, "CloudHeader must match Python struct '<dII'");

}  // namespace

int main() {
  std::signal(SIGINT, on_signal);
  std::signal(SIGTERM, on_signal);

  const std::string lidar_ip = env_or("LIDAR_IP", "192.168.1.62");
  const std::string local_ip = env_or("LOCAL_IP", "192.168.1.2");
  const auto lidar_port = static_cast<unsigned short>(std::stoi(env_or("LIDAR_PORT", "6101")));
  const auto local_port = static_cast<unsigned short>(std::stoi(env_or("LOCAL_PORT", "6201")));
  const std::string endpoint = env_or("ZMQ_ENDPOINT", "ipc:///tmp/spider_lidar.ipc");
  const int stride = std::max(1, std::stoi(env_or("POINT_STRIDE", "2")));
  const float range_min = std::stof(env_or("RANGE_MIN", "0.05"));
  const float range_max = std::stof(env_or("RANGE_MAX", "12"));

  void* ctx = zmq_ctx_new();
  void* pub = zmq_socket(ctx, ZMQ_PUB);
  int hwm = 4;  // the safety loop only wants the newest cloud
  zmq_setsockopt(pub, ZMQ_SNDHWM, &hwm, sizeof(hwm));
  if (zmq_bind(pub, endpoint.c_str()) != 0) {
    std::fprintf(stderr, "zmq_bind(%s) failed: %s\n", endpoint.c_str(), zmq_strerror(zmq_errno()));
    return 1;
  }

  UnitreeLidarReader* reader = createUnitreeLidarReader();
  if (reader->initializeUDP(lidar_port, lidar_ip, local_port, local_ip, 18, true, range_min,
                            range_max) != 0) {
    std::fprintf(stderr, "LiDAR UDP init failed (lidar %s:%u, local %s:%u)\n", lidar_ip.c_str(),
                 lidar_port, local_ip.c_str(), local_port);
    return 2;
  }
  reader->startLidarRotation();
  std::fprintf(stderr, "lidar_bridge: publishing on %s (stride %d)\n", endpoint.c_str(), stride);

  PointCloudUnitree cloud;
  LidarImuData imu;
  std::vector<float> buf;
  uint64_t clouds = 0;

  while (g_stop == 0) {
    const int type = reader->runParse();
    if (type == LIDAR_POINT_DATA_PACKET_TYPE && reader->getPointCloud(cloud)) {
      buf.clear();
      buf.reserve(cloud.points.size() / stride * 4 + 4);
      for (size_t i = 0; i < cloud.points.size(); i += stride) {
        const PointUnitree& p = cloud.points[i];
        buf.push_back(p.x);
        buf.push_back(p.y);
        buf.push_back(p.z);
        buf.push_back(p.intensity);
      }
      const CloudHeader hdr{cloud.stamp, cloud.id, static_cast<uint32_t>(buf.size() / 4)};
      zmq_send(pub, "cloud", 5, ZMQ_SNDMORE | ZMQ_DONTWAIT);
      zmq_send(pub, &hdr, sizeof(hdr), ZMQ_SNDMORE | ZMQ_DONTWAIT);
      zmq_send(pub, buf.data(), buf.size() * sizeof(float), ZMQ_DONTWAIT);
      if (++clouds % 100 == 0) {
        std::fprintf(stderr, "lidar_bridge: %llu clouds, last %zu points\n",
                     static_cast<unsigned long long>(clouds), buf.size() / 4);
      }
    } else if (type == LIDAR_IMU_DATA_PACKET_TYPE && reader->getImuData(imu)) {
      const double stamp = imu.info.stamp.sec + imu.info.stamp.nsec * 1e-9;
      const float d[10] = {imu.quaternion[0],          imu.quaternion[1],
                           imu.quaternion[2],          imu.quaternion[3],
                           imu.angular_velocity[0],    imu.angular_velocity[1],
                           imu.angular_velocity[2],    imu.linear_acceleration[0],
                           imu.linear_acceleration[1], imu.linear_acceleration[2]};
      zmq_send(pub, "imu", 3, ZMQ_SNDMORE | ZMQ_DONTWAIT);
      zmq_send(pub, &stamp, sizeof(stamp), ZMQ_SNDMORE | ZMQ_DONTWAIT);
      zmq_send(pub, d, sizeof(d), ZMQ_DONTWAIT);
    } else if (type == 0) {
      usleep(200);  // nothing parsed: do not spin a whole core
    }
  }

  std::fprintf(stderr, "lidar_bridge: stopping\n");
  reader->stopLidarRotation();
  reader->closeUDP();
  zmq_close(pub);
  zmq_ctx_term(ctx);
  return 0;
}
