// lidar_bridge: Unitree L2 (unilidar_sdk2, Ethernet/UDP) -> ZeroMQ PUB for the Python body.
//
// Messages (multipart):
//   ["cloud", struct{double stamp; uint32 id; uint32 n;}, float32[n*4] x,y,z,intensity]
//   ["imu",   double stamp,                              float32[10] quat xyzw, gyro xyz, acc xyz]
//
// Recording socket (only when ZMQ_RECORD_ENDPOINT is set, full point rate):
//   ["cloudx", struct{double stamp; uint32 id; uint32 n;}, float32[n*6] x,y,z,intensity,time,ring]
//   ["imux",   double stamp,                               float32[10] as above, every sample]
//
// Configuration via environment variables (defaults match the L2 factory settings):
//   LIDAR_IP=192.168.1.62 LIDAR_PORT=6101 LOCAL_IP=192.168.1.2 LOCAL_PORT=6201
//   ZMQ_ENDPOINT=ipc:///tmp/spider_lidar.ipc POINT_STRIDE=2 RANGE_MIN=0.05 RANGE_MAX=12
//   IMU_DECIMATE=10          average this many IMU samples into one message (the L2 reports 500 Hz)
//   ZMQ_RECORD_ENDPOINT=ipc:///tmp/spider_lidar_rec.ipc
//   LIDAR_SET_WORK_MODE=0    provisioning only: set the work mode, reset the LiDAR, then exit

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
  const int imu_decimate = std::max(1, std::stoi(env_or("IMU_DECIMATE", "10")));
  const std::string record_endpoint = env_or("ZMQ_RECORD_ENDPOINT", "");
  const std::string set_work_mode = env_or("LIDAR_SET_WORK_MODE", "");
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

  void* rec = nullptr;
  if (!record_endpoint.empty()) {
    rec = zmq_socket(ctx, ZMQ_PUB);
    int rec_hwm = 32;
    zmq_setsockopt(rec, ZMQ_SNDHWM, &rec_hwm, sizeof(rec_hwm));
    if (zmq_bind(rec, record_endpoint.c_str()) != 0) {
      std::fprintf(stderr, "zmq_bind(%s) failed: %s\n", record_endpoint.c_str(),
                   zmq_strerror(zmq_errno()));
      return 1;
    }
  }

  UnitreeLidarReader* reader = createUnitreeLidarReader();
  if (reader->initializeUDP(lidar_port, lidar_ip, local_port, local_ip, 18, true, range_min,
                            range_max) != 0) {
    std::fprintf(stderr, "LiDAR UDP init failed (lidar %s:%u, local %s:%u)\n", lidar_ip.c_str(),
                 lidar_port, local_ip.c_str(), local_port);
    return 2;
  }
  reader->startLidarRotation();
  if (!set_work_mode.empty()) {  // same sequence as Unitree's example_lidar_udp.cpp
    sleep(1);
    reader->setLidarWorkMode(static_cast<uint32_t>(std::stoul(set_work_mode)));
    sleep(1);
    reader->resetLidar();
    sleep(1);
    std::fprintf(stderr, "lidar_bridge: work mode %s set; LiDAR reset\n", set_work_mode.c_str());
    return 0;
  }
  std::fprintf(stderr, "lidar_bridge: publishing on %s (stride %d, IMU / %d)\n", endpoint.c_str(),
               stride, imu_decimate);

  PointCloudUnitree cloud;
  LidarImuData imu;
  std::vector<float> buf;
  std::vector<float> rec_buf;
  uint64_t clouds = 0;
  float imu_sum[6] = {0, 0, 0, 0, 0, 0};  // gyro xyz, accel xyz
  int imu_count = 0;

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
      if (rec != nullptr) {
        rec_buf.clear();
        rec_buf.reserve(cloud.points.size() * 6);
        for (const PointUnitree& p : cloud.points) {
          rec_buf.push_back(p.x);
          rec_buf.push_back(p.y);
          rec_buf.push_back(p.z);
          rec_buf.push_back(p.intensity);
          rec_buf.push_back(static_cast<float>(p.time));
          rec_buf.push_back(static_cast<float>(p.ring));
        }
        const CloudHeader rec_hdr{cloud.stamp, cloud.id, static_cast<uint32_t>(rec_buf.size() / 6)};
        zmq_send(rec, "cloudx", 6, ZMQ_SNDMORE | ZMQ_DONTWAIT);
        zmq_send(rec, &rec_hdr, sizeof(rec_hdr), ZMQ_SNDMORE | ZMQ_DONTWAIT);
        zmq_send(rec, rec_buf.data(), rec_buf.size() * sizeof(float), ZMQ_DONTWAIT);
      }
      if (++clouds % 100 == 0) {
        std::fprintf(stderr, "lidar_bridge: %llu clouds, last %zu points\n",
                     static_cast<unsigned long long>(clouds), buf.size() / 4);
      }
    } else if (type == LIDAR_IMU_DATA_PACKET_TYPE && reader->getImuData(imu)) {
      const double stamp = imu.info.stamp.sec + imu.info.stamp.nsec * 1e-9;
      if (rec != nullptr) {
        const float raw[10] = {imu.quaternion[0],          imu.quaternion[1],
                               imu.quaternion[2],          imu.quaternion[3],
                               imu.angular_velocity[0],    imu.angular_velocity[1],
                               imu.angular_velocity[2],    imu.linear_acceleration[0],
                               imu.linear_acceleration[1], imu.linear_acceleration[2]};
        zmq_send(rec, "imux", 4, ZMQ_SNDMORE | ZMQ_DONTWAIT);
        zmq_send(rec, &stamp, sizeof(stamp), ZMQ_SNDMORE | ZMQ_DONTWAIT);
        zmq_send(rec, raw, sizeof(raw), ZMQ_DONTWAIT);
      }
      for (int i = 0; i < 3; ++i) {  // average, so foot impacts do not alias into the tilt estimate
        imu_sum[i] += imu.angular_velocity[i];
        imu_sum[i + 3] += imu.linear_acceleration[i];
      }
      if (++imu_count >= imu_decimate) {
        const float n = static_cast<float>(imu_count);
        const float d[10] = {imu.quaternion[0], imu.quaternion[1], imu.quaternion[2],
                             imu.quaternion[3], imu_sum[0] / n,    imu_sum[1] / n,
                             imu_sum[2] / n,    imu_sum[3] / n,    imu_sum[4] / n,
                             imu_sum[5] / n};
        zmq_send(pub, "imu", 3, ZMQ_SNDMORE | ZMQ_DONTWAIT);
        zmq_send(pub, &stamp, sizeof(stamp), ZMQ_SNDMORE | ZMQ_DONTWAIT);
        zmq_send(pub, d, sizeof(d), ZMQ_DONTWAIT);
        std::fill(imu_sum, imu_sum + 6, 0.0F);
        imu_count = 0;
      }
    } else if (type == 0) {
      usleep(1000);  // nothing parsed: packets arrive at about 216 Hz, so 1 ms loses nothing
    }
  }

  std::fprintf(stderr, "lidar_bridge: stopping\n");
  reader->stopLidarRotation();
  reader->closeUDP();
  if (rec != nullptr) {
    zmq_close(rec);
  }
  zmq_close(pub);
  zmq_ctx_term(ctx);
  return 0;
}
